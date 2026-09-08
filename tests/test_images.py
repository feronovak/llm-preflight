import pytest

from llm_preflight.images import prepare_image_inputs


def _png(width: int = 1, height: int = 1) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )


@pytest.mark.parametrize(
    ("name", "data", "mime_type", "dimensions"),
    [
        ("image.gif", b"GIF89a\x02\x00\x03\x00", "image/gif", (2, 3)),
        (
            "image.jpg",
            b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x02\x00\x03" + b"\x00" * 10,
            "image/jpeg",
            (3, 2),
        ),
        (
            "image.webp",
            b"RIFF\x00\x00\x00\x00WEBPVP8X" + b"\x00" * 8 + b"\x01\x00\x00\x02\x00\x00",
            "image/webp",
            (2, 3),
        ),
    ],
)
def test_prepare_image_inputs_accepts_supported_non_png_headers(
    tmp_path, name, data, mime_type, dimensions
):
    (tmp_path / name).write_bytes(data)
    request = {"input_images": [{"path": name, "mime_type": mime_type}]}

    prepare_image_inputs(request, tmp_path, "request")

    assert (
        request["input_images"][0]["width"],
        request["input_images"][0]["height"],
    ) == dimensions


def test_prepare_image_inputs_rejects_empty_absolute_and_symlink_escape(tmp_path):
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(_png())
    link = tmp_path / "escape.png"
    link.symlink_to(outside)

    with pytest.raises(ValueError, match="non-empty list"):
        prepare_image_inputs({"input_images": []}, tmp_path, "request")
    with pytest.raises(ValueError, match="must be relative"):
        prepare_image_inputs(
            {"input_images": [{"path": str(outside), "mime_type": "image/png"}]},
            tmp_path,
            "request",
        )
    with pytest.raises(ValueError, match="must stay within the config directory"):
        prepare_image_inputs(
            {"input_images": [{"path": "escape.png", "mime_type": "image/png"}]},
            tmp_path,
            "request",
        )


def test_prepare_image_inputs_rejects_byte_and_pixel_limits(tmp_path, monkeypatch):
    from llm_preflight import images

    image = tmp_path / "image.png"
    image.write_bytes(_png() + b"padding")
    monkeypatch.setattr(images, "MAX_IMAGE_BYTES", 20)

    with pytest.raises(ValueError, match="between 1 byte"):
        prepare_image_inputs(
            {"input_images": [{"path": "image.png", "mime_type": "image/png"}]},
            tmp_path,
            "request",
        )

    monkeypatch.setattr(images, "MAX_IMAGE_BYTES", 10 * 1024 * 1024)
    image.write_bytes(_png(10_000, 10_000))
    with pytest.raises(ValueError, match="pixel safety limit"):
        prepare_image_inputs(
            {"input_images": [{"path": "image.png", "mime_type": "image/png"}]},
            tmp_path,
            "request",
        )
