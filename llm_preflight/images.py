"""Safe, local image inputs for vision-to-text preflight requests."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Any

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
_DATA_URL = re.compile(
    r"^data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/]*={0,2})$"
)


def prepare_image_inputs(
    request: dict[str, Any], base_dir: Path | None, location: str
) -> None:
    """Validate configured local images and attach non-sensitive evidence."""
    inputs = request.get("input_images")
    if inputs is None:
        return
    if base_dir is None:
        raise ValueError(f"{location}.input_images requires a configuration file")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError(f"{location}.input_images must be a non-empty list")
    for index, image in enumerate(inputs):
        item_location = f"{location}.input_images[{index}]"
        if not isinstance(image, dict) or set(image) - {
            "path",
            "mime_type",
            "data_url",
            "sha256",
            "width",
            "height",
            "source",
            "_data_base64",
        }:
            raise ValueError(
                f"{item_location} requires either path and mime_type, or data_url"
            )
        if image.get("source") == "path" and isinstance(image.get("sha256"), str):
            continue
        initial_keys = {"path", "mime_type"}
        if image.get("source") == "data_url" and isinstance(
            image.get("_data_base64"), str
        ):
            data_url_mime = image.get("mime_type")
            data = base64.b64decode(image["_data_base64"], validate=True)
            source = "data_url"
        elif "data_url" in image:
            initial_keys = {"data_url"}
            data_url_mime, data = _read_data_url(image["data_url"], item_location)
            source = "data_url"
        else:
            data_url_mime = None
            source = "path"
        if source == "path" and set(image) - initial_keys:
            image = {key: image[key] for key in ("path", "mime_type") if key in image}
            if "data_url" in inputs[index]:
                image = {"data_url": inputs[index]["data_url"]}
            inputs[index] = image
        if source == "path":
            path, data = _read_image(image, base_dir, item_location)
        mime_type = _mime_type(data)
        if data_url_mime is not None and data_url_mime != mime_type:
            raise ValueError(
                f"{item_location}.data_url MIME type must match file content"
            )
        if source == "path" and image.get("mime_type") != mime_type:
            raise ValueError(
                f"{item_location}.mime_type must match the file content ({mime_type})"
            )
        width, height = _dimensions(data, mime_type, item_location)
        if width * height > MAX_IMAGE_PIXELS:
            raise ValueError(
                f"{item_location} exceeds the {MAX_IMAGE_PIXELS:,} pixel safety limit"
            )
        image.update(
            {
                "mime_type": mime_type,
                "width": width,
                "height": height,
                "sha256": hashlib.sha256(data).hexdigest(),
                "source": source,
            }
        )
        if source == "path":
            image["path"] = path.as_posix()
        else:
            image.pop("data_url", None)
            image["_data_base64"] = base64.b64encode(data).decode("ascii")


def input_image_parts(options: dict[str, Any]) -> list[dict[str, str]]:
    """Read verified local inputs only while constructing a provider request."""
    inputs = options.get("input_images")
    if not inputs:
        return []
    base_dir_value = options.get("_image_base_dir")
    if not isinstance(base_dir_value, str):
        raise ValueError("input_images require a configuration file")  # noqa: TRY004
    base_dir = Path(base_dir_value)
    parts = []
    for index, image in enumerate(inputs):
        location = f"request.input_images[{index}]"
        if not isinstance(image, dict):
            raise ValueError(f"{location} must be an object")  # noqa: TRY004
        if image.get("source") == "data_url":
            encoded = image.get("_data_base64")
            if not isinstance(encoded, str):
                raise ValueError(f"{location} requires the original configuration file")
            data = base64.b64decode(encoded, validate=True)
        else:
            _path, data = _read_image(image, base_dir, location)
        mime_type = _mime_type(data)
        if image.get("mime_type") != mime_type:
            raise ValueError(f"{location}.mime_type no longer matches the file content")
        expected = image.get("sha256")
        actual = hashlib.sha256(data).hexdigest()
        if not isinstance(expected, str) or expected != actual:
            raise ValueError(f"{location} changed after configuration was loaded")
        parts.append(
            {
                "mime_type": mime_type,
                "data": base64.b64encode(data).decode("ascii"),
            }
        )
    return parts


def _read_data_url(value: Any, location: str) -> tuple[str, bytes]:
    if not isinstance(value, str):
        raise ValueError(f"{location}.data_url must be a string")  # noqa: TRY004
    match = _DATA_URL.fullmatch(value)
    if not match:
        raise ValueError(
            f"{location}.data_url must be a base64 PNG, JPEG, WEBP, or GIF"
        )
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except ValueError as exc:
        raise ValueError(f"{location}.data_url is not valid base64") from exc
    if not 0 < len(data) <= MAX_IMAGE_BYTES:
        raise ValueError(
            f"{location}.data_url must be between 1 byte and {MAX_IMAGE_BYTES} bytes"
        )
    return match.group(1), data


def _read_image(
    image: dict[str, Any], base_dir: Path, location: str
) -> tuple[Path, bytes]:
    configured_path = image.get("path")
    if not isinstance(configured_path, str) or not configured_path:
        raise ValueError(f"{location}.path must be a non-empty relative path")
    path = Path(configured_path)
    if path.is_absolute():
        raise ValueError(f"{location}.path must be relative")
    resolved_base = base_dir.resolve()
    resolved_path = (resolved_base / path).resolve()
    if resolved_base != resolved_path and resolved_base not in resolved_path.parents:
        raise ValueError(f"{location}.path must stay within the config directory")
    if not resolved_path.is_file():
        raise ValueError(f"{location}.path does not exist or is not a file")
    size = resolved_path.stat().st_size
    if not 0 < size <= MAX_IMAGE_BYTES:
        raise ValueError(
            f"{location}.path must be between 1 byte and {MAX_IMAGE_BYTES} bytes"
        )
    return path, resolved_path.read_bytes()


def _mime_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("input image must be a PNG, JPEG, WEBP, or GIF file")


def _dimensions(data: bytes, mime_type: str, location: str) -> tuple[int, int]:
    if mime_type == "image/png" and len(data) >= 24 and data[12:16] == b"IHDR":
        return _valid_dimensions(
            int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"),
            location,
        )
    if mime_type == "image/gif" and len(data) >= 10:
        return _valid_dimensions(
            int.from_bytes(data[6:8], "little"),
            int.from_bytes(data[8:10], "little"),
            location,
        )
    if mime_type == "image/jpeg":
        return _jpeg_dimensions(data, location)
    if mime_type == "image/webp":
        return _webp_dimensions(data, location)
    raise ValueError(f"{location} has an incomplete image header")


def _valid_dimensions(width: int, height: int, location: str) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ValueError(f"{location} has invalid image dimensions")
    return width, height


def _jpeg_dimensions(data: bytes, location: str) -> tuple[int, int]:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            break
        length = int.from_bytes(data[index : index + 2], "big")
        if length < 2 or index + length > len(data):
            break
        if 0xC0 <= marker <= 0xC3 or 0xC5 <= marker <= 0xC7 or 0xC9 <= marker <= 0xCB:
            return _valid_dimensions(
                int.from_bytes(data[index + 5 : index + 7], "big"),
                int.from_bytes(data[index + 3 : index + 5], "big"),
                location,
            )
        index += length
    raise ValueError(f"{location} has an incomplete JPEG header")


def _webp_dimensions(data: bytes, location: str) -> tuple[int, int]:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        return _valid_dimensions(
            int.from_bytes(data[24:27], "little") + 1,
            int.from_bytes(data[27:30], "little") + 1,
            location,
        )
    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return _valid_dimensions(
            (bits & 0x3FFF) + 1,
            ((bits >> 14) & 0x3FFF) + 1,
            location,
        )
    if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        return _valid_dimensions(
            int.from_bytes(data[26:28], "little") & 0x3FFF,
            int.from_bytes(data[28:30], "little") & 0x3FFF,
            location,
        )
    raise ValueError(f"{location} has an incomplete WEBP header")
