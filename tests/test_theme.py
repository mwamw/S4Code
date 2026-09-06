from pathlib import Path

from s4code.interfaces.terminal.theme import list_bundled_themes, load_tui_theme


def test_loads_bundled_themes_with_default_fallbacks() -> None:
    themes = list_bundled_themes()

    assert {"s4", "graphite", "ember", "forest", "aurora"}.issubset(set(themes))
    for name in themes:
        theme = load_tui_theme(name)
        assert theme["name"]
        assert theme["layout"]["input_border"]
        assert theme["cards"]["assistant"]["border"]
        assert theme["palette"]["border"]
        assert theme["diff"]["add_prefix"]


def test_loads_theme_from_json_path(tmp_path: Path) -> None:
    theme_path = tmp_path / "custom.json"
    theme_path.write_text(
        """
        {
          "name": "custom",
          "layout": {
            "input_border": "#ffffff"
          },
          "cards": {
            "assistant": {
              "border": "#123456"
            }
          }
        }
        """,
        encoding="utf-8",
    )

    theme = load_tui_theme(str(theme_path))

    assert theme["name"] == "custom"
    assert theme["layout"]["input_border"] == "#ffffff"
    assert theme["layout"]["transcript_border"]
    assert theme["cards"]["assistant"]["border"] == "#123456"
    assert theme["palette"]["border"]
