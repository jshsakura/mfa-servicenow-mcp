"""The pixel cap on screenshots.

A model is billed for an image's PIXEL COUNT. The WebP work elsewhere cuts the
file to 40% of the PNG and saves nothing here — the same pixels arrive either
way. These pin the axis that actually costs tokens.
"""

import io
import os

import pytest

from servicenow_mcp.browser import image_budget

Image = pytest.importorskip("PIL.Image")


def _img(width, height):
    return Image.new("RGB", (width, height), "white")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("SERVICENOW_SCREENSHOT_MAX_WIDTH", raising=False)


def test_a_wide_shot_is_capped_and_says_so():
    fitted, size = image_budget.fit(_img(1729, 847))
    assert fitted.width == image_budget.DEFAULT_MAX_WIDTH
    # Aspect ratio preserved: 847 * 1024/1729 == 502.
    assert fitted.height == 502
    assert size == {"pixels": "1024x502", "downscaled_from": "1729x847"}


def test_a_small_shot_is_never_upscaled():
    """An element shot is already cheap; stretching it spends tokens to add
    nothing, and would report a resize that improved nothing."""
    fitted, size = image_budget.fit(_img(300, 120))
    assert (fitted.width, fitted.height) == (300, 120)
    assert size == {"pixels": "300x120"}
    assert "downscaled_from" not in size


def test_a_tall_stitch_keeps_its_width_axis():
    """Width, not the longer side. Capping the long edge of a several-screen
    capture would crush the axis that carries legibility."""
    fitted, _ = image_budget.fit(_img(1729, 6776))
    assert fitted.width == 1024
    assert fitted.height == 4013


def test_the_cap_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("SERVICENOW_SCREENSHOT_MAX_WIDTH", "off")
    fitted, size = image_budget.fit(_img(1729, 847))
    assert fitted.width == 1729
    assert size == {"pixels": "1729x847"}


@pytest.mark.parametrize("value,expected", [("1400", 1400), ("64", image_budget.MIN_MAX_WIDTH)])
def test_the_cap_is_configurable_with_a_floor(monkeypatch, value, expected):
    """Below the floor a UI screenshot can no longer answer a visual question,
    so an unusable setting is corrected rather than honoured."""
    monkeypatch.setenv("SERVICENOW_SCREENSHOT_MAX_WIDTH", value)
    assert image_budget.max_width() == expected


def test_a_nonsense_setting_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("SERVICENOW_SCREENSHOT_MAX_WIDTH", "wide-ish")
    assert image_budget.max_width() == image_budget.DEFAULT_MAX_WIDTH


def test_the_written_file_reports_the_size_it_actually_produced(tmp_path):
    """A resize that did not happen must not be reported as one that did."""
    from servicenow_mcp.browser import capture

    buffer = io.BytesIO()
    _img(1729, 847).save(buffer, "PNG")
    path, size = capture._write_image(buffer.getvalue(), str(tmp_path / "shot.png"))

    assert os.path.exists(path)
    with Image.open(path) as written:
        assert (written.width, written.height) == (1024, 502)
    assert size["pixels"] == "1024x502"
    assert size["downscaled_from"] == "1729x847"


def test_a_png_is_measured_without_an_image_library():
    """The size must be reportable exactly where Pillow is missing — that is
    the case where nothing was capped, so it is where the number matters."""
    buffer = io.BytesIO()
    _img(1729, 847).save(buffer, "PNG")
    assert image_budget.png_size(buffer.getvalue()) == (1729, 847)


@pytest.mark.parametrize("raw", [b"", b"not a png at all", b"\x89PNG\r\n\x1a\n" + b"\x00" * 4])
def test_a_non_png_measures_to_nothing_rather_than_a_guess(raw):
    assert image_budget.png_size(raw) is None


def test_an_uncapped_screenshot_says_it_was_not_capped():
    """A missing size next to a cost note that says 'consult the size' reads as
    'capped'. The reply states plainly that it is not, and why."""
    buffer = io.BytesIO()
    _img(1729, 847).save(buffer, "PNG")
    out = image_budget.uncapped(buffer.getvalue())

    assert out["pixels_capped"] == "no"
    assert out["pixels"] == "1729x847"
    assert "Pillow" in out["reason"] and "full size" in out["reason"]


def test_an_unmeasurable_uncapped_screenshot_still_says_it_was_not_capped():
    out = image_budget.uncapped(b"not a png")
    assert out["pixels_capped"] == "no"
    assert "pixels" not in out


def test_the_no_pillow_path_reports_uncapped(tmp_path, monkeypatch):
    """Pin the branch that runs in every deployment that lacks Pillow."""
    import builtins

    from servicenow_mcp.browser import capture

    real_import = builtins.__import__

    def _no_pil(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no PIL")
        return real_import(name, *args, **kwargs)

    buffer = io.BytesIO()
    _img(1729, 847).save(buffer, "PNG")
    monkeypatch.setattr(builtins, "__import__", _no_pil)
    path, size = capture._write_image(buffer.getvalue(), str(tmp_path / "shot.png"))

    assert path.endswith(".png"), "without Pillow the bytes are written as they came"
    assert size["pixels_capped"] == "no"
    assert size["pixels"] == "1729x847"
