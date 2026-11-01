"""sidekick.body.model — the Reachy Mini URDF reduced to a display model for the dashboard's 3D view

Overview
    Reads `robot.urdf` shipped inside the installed `reachy_mini` package and turns it into a
    small JSON document the browser can render with Three.js: a handful of rigid groups (base,
    torso, head, two antennas, six motor horns), each with an allowlisted set of STL meshes and
    their 4x4 placement matrices, plus the geometry of the six Stewart legs (ball on the horn,
    anchor on the head) so they can be drawn as straight rods. `mesh_path()` resolves an
    allowlisted mesh name to the SDK file for read-only serving.
Design
    Forward kinematics at the URDF zero configuration gives every link's world frame; mesh
    matrices are re-expressed in the group frame the browser animates: `head` (the SDK's `head`
    frame, identity rotation at rest, `HEAD_REST_Z` = 0.177 m above the foot, so a reported head
    pose `H` renders as `T(0, 0, 0.177) · H`), `torso` (`body_down`, rotated by the body yaw),
    the two antenna joints (fixed in `head`) and the six `stewart_i` joints (fixed in `torso`).
    Only ~30 of the 175 meshes are kept — shells, lenses, antennas, horns, arms, balls — because
    screws and motor cases are invisible inside the shell and would triple the download. Matrices
    are row-major lists of 16 floats, metres and radians. Parsing is stdlib `xml.etree` + numpy
    and cached for the process; the SDK is only a file source here, never imported.
Depends on
    numpy.

See Also
--------
    AGENTS.md "Body", PLAN.md block "[2026-10-26 #25]".

"""

from __future__ import annotations

import functools
import importlib.util
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

Matrix = npt.NDArray[np.float64]

HEAD_REST_Z = 0.177
HORN_BALL = (0.04, 0.0, 0.007)
ROD_LENGTH = 0.085

BASE_MESHES = frozenset({"body_foot_3dprint.stl", "body_turning_3dprint.stl"})
TORSO_MESHES = frozenset(
    {
        "body_down_3dprint.stl",
        "body_top_3dprint.stl",
        "stewart_main_plate_3dprint.stl",
        "stewart_tricap_3dprint.stl",
        "5w_speaker.stl",
        "bearing_85x110x13.stl",
    }
)
HEAD_MESHES = frozenset(
    {
        "head_front_3dprint.stl",
        "head_back_3dprint.stl",
        "neck_reference_3dprint.stl",
        "head_mic_3dprint.stl",
        "glasses_dolder_3dprint.stl",
        "big_lens.stl",
        "big_lens_d40.stl",
        "small_lens_d30.stl",
        "lens_cap_d30_3dprint.stl",
        "lens_cap_d40_3dprint.stl",
        "antenna_holder_l_3dprint.stl",
        "antenna_holder_r_3dprint.stl",
        "arducam.stl",
        "pp01102_arducam_carter.stl",
        "m12_fisheye_lens_1_8mm.stl",
        "stewart_link_ball__2.stl",
    }
)
ARM_MESHES = frozenset(
    {"dc15_a01_horn_dummy.stl", "mp01062_stewart_arm_3.stl", "stewart_link_ball.stl"}
)
ANTENNA_MESHES = frozenset(
    {"antenna.stl", "antenna_body_3dprint.stl", "antenna_interface_3dprint.stl"}
)
ALLOWED_MESHES = BASE_MESHES | TORSO_MESHES | HEAD_MESHES | ARM_MESHES | ANTENNA_MESHES
MESH_NAME = re.compile(r"^[a-z0-9_]+\.stl$")

HORN_LINKS = {
    1: "dc15_a01_horn_dummy",
    2: "dc15_a01_horn_dummy_2",
    3: "dc15_a01_horn_dummy_3",
    4: "dc15_a01_horn_dummy_4",
    5: "dc15_a01_horn_dummy_5",
    6: "dc15_a01_horn_dummy_6",
}
ANCHOR_LINKS = {
    1: "closing_1_2",
    2: "closing_2_2",
    3: "closing_3_2",
    4: "closing_4_2",
    5: "closing_5_2",
    6: "xl_330",
}


def urdf_dir() -> Path | None:
    """`descriptions/reachy_mini/urdf` inside the installed SDK, or None without the SDK."""
    spec = importlib.util.find_spec("reachy_mini")
    if spec is None or not spec.origin:
        return None
    path = Path(spec.origin).parent / "descriptions" / "reachy_mini" / "urdf"
    return path if (path / "robot.urdf").exists() else None


def _rotation(roll: float, pitch: float, yaw: float) -> Matrix:
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=np.float64)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=np.float64)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=np.float64)
    return rz @ ry @ rx


def _origin(element: ET.Element | None) -> Matrix:
    """4x4 from a URDF `<origin xyz rpy>` (identity when absent)."""
    out = np.eye(4, dtype=np.float64)
    if element is None:
        return out
    xyz = [float(v) for v in (element.get("xyz") or "0 0 0").split()]
    rpy = [float(v) for v in (element.get("rpy") or "0 0 0").split()]
    out[:3, :3] = _rotation(*rpy)
    out[:3, 3] = xyz
    return out


def _flat(matrix: Matrix) -> list[float]:
    return [round(float(v), 6) + 0.0 for v in matrix.reshape(-1)]


class _Urdf:
    """Links, joints and zero-configuration forward kinematics."""

    def __init__(self, path: Path) -> None:
        root = ET.parse(path).getroot()
        self.links: dict[str, ET.Element] = {
            str(link.get("name")): link for link in root.findall("link")
        }
        self.joints: dict[str, ET.Element] = {
            str(joint.get("name")): joint for joint in root.findall("joint")
        }
        self.parent: dict[str, tuple[str, Matrix]] = {}
        for joint in self.joints.values():
            parent = joint.find("parent")
            child = joint.find("child")
            if parent is None or child is None:
                continue
            self.parent[str(child.get("link"))] = (
                str(parent.get("link")),
                _origin(joint.find("origin")),
            )

    def world(self, link: str) -> Matrix:
        """Link frame in the root frame at the zero configuration."""
        out = np.eye(4, dtype=np.float64)
        while link in self.parent:
            parent, transform = self.parent[link]
            out = transform @ out
            link = parent
        return out

    def joint_origin(self, name: str) -> Matrix:
        """The joint frame in its parent link."""
        return _origin(self.joints[name].find("origin"))

    def visuals(self, link: str, allowed: frozenset[str]) -> list[tuple[str, Matrix]]:
        """`(mesh file, placement in link frame)` for the allowlisted visuals of a link."""
        out: list[tuple[str, Matrix]] = []
        element = self.links.get(link)
        if element is None:
            return out
        for visual in element.findall("visual"):
            mesh = visual.find("geometry/mesh")
            if mesh is None:
                continue
            name = str(mesh.get("filename") or "").split("/")[-1]
            if name in allowed:
                out.append((name, _origin(visual.find("origin"))))
        return out


def build_display_model(urdf_path: Path) -> dict[str, Any]:
    """The JSON document `/api/body/model` serves."""
    urdf = _Urdf(urdf_path)
    world_head = urdf.world("head")
    head_inv = np.linalg.inv(world_head)
    world_xl = urdf.world("xl_330")
    xl_to_head = head_inv @ world_xl  # xl_330 visuals expressed in the head frame

    def meshes(link: str, allowed: frozenset[str], pre: Matrix | None = None) -> list[Any]:
        return [
            {"file": name, "matrix": _flat((pre if pre is not None else np.eye(4)) @ placement)}
            for name, placement in urdf.visuals(link, allowed)
        ]

    groups: list[dict[str, Any]] = [
        {
            "name": "base",
            "parent": None,
            "matrix": _flat(np.eye(4)),
            "meshes": meshes("body_foot_3dprint", BASE_MESHES),
        },
        {
            "name": "torso",
            "parent": "base",
            "matrix": _flat(urdf.joint_origin("yaw_body")),
            "joint": "body_yaw",
            "axis": [0.0, 0.0, 1.0],
            "meshes": meshes("body_down_3dprint", TORSO_MESHES),
        },
        {
            "name": "head",
            "parent": "base",
            "matrix": _flat(
                np.array(
                    [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, HEAD_REST_Z], [0, 0, 0, 1]],
                    dtype=np.float64,
                )
            ),
            "joint": "head_pose",
            "meshes": meshes("xl_330", HEAD_MESHES, xl_to_head),
        },
    ]
    for side, joint, link in (
        ("right", "right_antenna", "dc15_a01_horn_dummy_7"),
        ("left", "left_antenna", "dc15_a01_horn_dummy_8"),
    ):
        groups.append(
            {
                "name": f"antenna_{side}",
                "parent": "head",
                "matrix": _flat(xl_to_head @ urdf.joint_origin(joint)),
                "joint": f"antenna_{side}",
                "axis": [0.0, 0.0, 1.0],
                "meshes": meshes(link, ANTENNA_MESHES),
            }
        )
    rods: list[dict[str, Any]] = []
    for index in range(1, 7):
        groups.append(
            {
                "name": f"arm_{index}",
                "parent": "torso",
                "matrix": _flat(urdf.joint_origin(f"stewart_{index}")),
                "joint": f"stewart_{index}",
                "axis": [0.0, 0.0, 1.0],
                "meshes": meshes(HORN_LINKS[index], ARM_MESHES),
            }
        )
        anchor = head_inv @ urdf.world(ANCHOR_LINKS[index])
        rods.append(
            {
                "arm": f"arm_{index}",
                "ball": list(HORN_BALL),
                "anchor": [round(float(v), 6) + 0.0 for v in anchor[:3, 3]],
            }
        )
    camera = head_inv @ urdf.world("camera")
    return {
        "available": True,
        "units": "m",
        "head_rest_z": HEAD_REST_Z,
        "rod_length": ROD_LENGTH,
        "camera_in_head": _flat(camera),
        "groups": groups,
        "rods": rods,
        "meshes": sorted({m["file"] for g in groups for m in g["meshes"]}),
    }


@functools.lru_cache(maxsize=1)
def display_model() -> dict[str, Any]:
    """Cached model from the installed SDK; `{"available": False}` without it."""
    directory = urdf_dir()
    if directory is None:
        return {"available": False, "groups": [], "rods": [], "meshes": []}
    return build_display_model(directory / "robot.urdf")


def mesh_path(name: str) -> Path | None:
    """The STL file for an allowlisted mesh name, if the SDK ships it."""
    if not MESH_NAME.match(name) or name not in ALLOWED_MESHES:
        return None
    directory = urdf_dir()
    if directory is None:
        return None
    path = directory / "assets" / name
    return path if path.is_file() else None
