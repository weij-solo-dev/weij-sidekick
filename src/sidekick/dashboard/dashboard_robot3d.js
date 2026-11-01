/* sidekick dashboard — 3D Reachy Mini (Three.js r160, vendored). Loads /api/body/model (the SDK URDF
   reduced to rigid groups + allowlisted STL meshes) and animates it from telemetry: the head group
   is placed by the measured 4x4 head pose (commanded Euler pose as fallback), the torso and the six
   motor horns rotate by the measured joints, antennas by angle, and the Stewart rods are straight
   cylinders between each horn ball and its head anchor (no platform solve; PLAN.md #24 decision 5).
   Views are created per container (Live, Replay) and share the geometry cache. */
import * as THREE from "three";
import { STLLoader } from "./dashboard_stl_loader.js";
import { OrbitControls } from "./dashboard_orbit_controls.js";

const geometries = new Map();
const loader = new STLLoader();
let modelPromise = null;

const COLORS = {
  base: 0xe9e9ee, torso: 0xf1f1f4, head: 0xf4f4f6, antenna_right: 0xd7d7dc, antenna_left: 0xd7d7dc,
  arm: 0x3a3d45, rod: 0x8b93a7, lens: 0x202329, ball: 0x55585f,
};
const DARK = new Set(["big_lens.stl", "big_lens_d40.stl", "small_lens_d30.stl", "m12_fisheye_lens_1_8mm.stl", "arducam.stl", "5w_speaker.stl", "bearing_85x110x13.stl"]);

function geometry(file) {
  if (!geometries.has(file)) geometries.set(file, loader.loadAsync(`/api/body/mesh/${file}`).then((g) => { g.computeVertexNormals(); return g; }));
  return geometries.get(file);
}
function model() {
  if (!modelPromise) modelPromise = fetch("/api/body/model").then((r) => r.json());
  return modelPromise;
}
function matrixFrom(list) { const m = new THREE.Matrix4(); m.set(...list); return m; }
function eulerPose(h) {
  // same convention as body/schemas.head_pose: Rz(yaw) · Ry(pitch) · Rx(roll), translation z
  const m = new THREE.Matrix4();
  const e = new THREE.Euler(h[2], h[1], h[0], "ZYX");
  m.makeRotationFromEuler(e);
  m.setPosition(0, 0, h[3] || 0);
  return m;
}

export function create(container) {
  const view = { container, running: false, dirty: true, ready: false, groups: {}, joints: {}, rods: [], last: null };
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 16 / 9, 0.02, 10);
  camera.position.set(0.56, 0.34, 0.46);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0.16, 0);
  controls.enableDamping = true; controls.dampingFactor = 0.12;
  controls.minDistance = 0.15; controls.maxDistance = 2.0;
  controls.addEventListener("change", () => { view.dirty = true; });
  scene.add(new THREE.HemisphereLight(0xffffff, 0x3a3f55, 1.15));
  const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(0.6, 1.2, 0.8); scene.add(key);
  const fill = new THREE.DirectionalLight(0x8fb6ff, 0.5); fill.position.set(-0.8, 0.4, -0.6); scene.add(fill);
  const grid = new THREE.GridHelper(0.6, 12, 0x3a4150, 0x262b36); grid.position.y = 0; scene.add(grid);
  const root = new THREE.Group(); root.rotation.x = -Math.PI / 2; scene.add(root); // robot z-up → three y-up

  function resize() {
    const w = container.clientWidth || 320, h = container.clientHeight || 180;
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    view.dirty = true;
  }
  const ro = new ResizeObserver(resize); ro.observe(container);
  resize();

  function frame() {
    if (!view.running) return;
    controls.update();
    if (view.dirty) { renderer.render(scene, camera); view.dirty = false; }
    requestAnimationFrame(frame);
  }

  model().then(async (m) => {
    if (!m.available) { container.insertAdjacentHTML("beforeend", '<span class="hint">no robot model (SDK not installed)</span>'); return; }
    const mounts = {};
    for (const g of m.groups) {
      const mount = new THREE.Group(); mount.matrixAutoUpdate = false; mount.matrix.copy(matrixFrom(g.matrix));
      const joint = new THREE.Group();
      mount.add(joint);
      (g.parent ? view.joints[g.parent] : root).add(mount);
      mounts[g.name] = mount; view.joints[g.name] = joint; view.groups[g.name] = g;
      const color = COLORS[g.name] || (g.name.startsWith("arm_") ? COLORS.arm : 0xcccccc);
      for (const part of g.meshes) {
        geometry(part.file).then((geo) => {
          const dark = DARK.has(part.file) || part.file.includes("ball");
          const mat = new THREE.MeshStandardMaterial({ color: dark ? (part.file.includes("ball") ? COLORS.ball : COLORS.lens) : color, roughness: dark ? 0.45 : 0.6, metalness: dark ? 0.3 : 0.05 });
          const mesh = new THREE.Mesh(geo, mat); mesh.matrixAutoUpdate = false; mesh.matrix.copy(matrixFrom(part.matrix));
          joint.add(mesh); view.dirty = true;
        }).catch((e) => console.warn("mesh", part.file, e));
      }
    }
    const rodGeo = new THREE.CylinderGeometry(0.0022, 0.0022, 1, 10);
    rodGeo.rotateX(Math.PI / 2); // along +z, scaled to the rod length
    for (const r of m.rods) {
      const mesh = new THREE.Mesh(rodGeo, new THREE.MeshStandardMaterial({ color: COLORS.rod, roughness: 0.5, metalness: 0.4 }));
      root.add(mesh);
      view.rods.push({ mesh, arm: r.arm, ball: new THREE.Vector3(...r.ball), anchor: new THREE.Vector3(...r.anchor) });
    }
    view.ready = true;
    if (view.last) view.setPose(view.last);
    view.dirty = true;
  }).catch((e) => console.warn("model", e));

  const tmpA = new THREE.Vector3(), tmpB = new THREE.Vector3(), tmpM = new THREE.Matrix4();
  view.setPose = (b) => {
    view.last = b;
    if (!view.ready || !b) return;
    const J = view.joints;
    const headPose = b.head_measured && b.head_measured.length === 16 ? matrixFrom(b.head_measured) : eulerPose(b.head);
    J.head.matrixAutoUpdate = false; J.head.matrix.copy(headPose);
    const joints = b.joints_measured;
    J.torso.rotation.z = joints ? joints[0] : 0;
    for (let i = 1; i <= 6; i++) if (J[`arm_${i}`]) J[`arm_${i}`].rotation.z = joints && joints.length >= 7 ? joints[i] : 0;
    const ant = b.antennas_measured || b.antennas;
    if (J.antenna_right) J.antenna_right.rotation.z = ant[0];
    if (J.antenna_left) J.antenna_left.rotation.z = ant[1];
    root.updateMatrixWorld(true);
    for (const r of view.rods) {
      J[r.arm].localToWorld(tmpA.copy(r.ball));
      J.head.localToWorld(tmpB.copy(r.anchor));
      root.worldToLocal(tmpA); root.worldToLocal(tmpB);
      const len = tmpA.distanceTo(tmpB);
      r.mesh.position.copy(tmpA).lerp(tmpB, 0.5);
      r.mesh.scale.set(1, 1, Math.max(0.001, len));
      tmpM.lookAt(tmpA, tmpB, new THREE.Vector3(0, 0, 1));
      r.mesh.quaternion.setFromRotationMatrix(tmpM);
    }
    view.dirty = true;
  };
  view.resume = () => { if (!view.running) { view.running = true; view.dirty = true; requestAnimationFrame(frame); } };
  view.pause = () => { view.running = false; };
  view.dispose = () => { view.pause(); ro.disconnect(); renderer.dispose(); container.innerHTML = ""; };
  return view;
}

window.SidekickRobot3D = { create, model };
window.dispatchEvent(new Event("robot3d-ready"));
