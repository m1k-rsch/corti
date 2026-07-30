"""Textual TUI for ``cortistrate demo``."""

from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Footer, Static

from cortistrate.entrypoints.tui.demo.data import DemoStory, default_demo_story
from cortistrate.entrypoints.tui.demo.widgets.sphere import (
    CORTISTRATE_AMBER,
    CORTISTRATE_AMBER_DIM,
    CORTISTRATE_CYAN,
    CORTISTRATE_GREEN,
    CORTISTRATE_ORANGE,
    CORTISTRATE_YELLOW,
    CORTISTRATE_YELLOW_SOFT,
    build_dot_sphere,
    render_dot_sphere_text,
)

CORTISTRATE_BLACK = "#1D1C18"
CORTISTRATE_SURFACE = "#24231E"
CORTISTRATE_SURFACE_RAISED = "#31302B"
CORTISTRATE_INK = "#F5EDDC"
CORTISTRATE_MUTED = "#918C80"
CORTISTRATE_BORDER = "#5A5549"
SPHERE_FRAME_WIDTH = 37
SPHERE_FRAME_HEIGHT = 17
TERMINAL_CELL_HEIGHT_RATIO = 2.0
SIGNAL_RAIL_SOURCE_WIDTH = 18


class DotSphereWidget(Static):
    """Animated dot sphere that represents Cortistrate memory activity."""

    DEFAULT_CSS = """
    DotSphereWidget {
        height: 1fr;
        content-align: center middle;
    }
    """

    STATES = (
        "booting",
        "ingesting",
        "extracting",
        "indexing",
        "recalling",
        "remembered",
        "source",
        "celebrating",
    )

    def __init__(self) -> None:
        super().__init__()
        self._phase = 0.0
        self._tick = 0
        self._animation_timer: Timer | None = None

    def on_mount(self) -> None:
        self._animation_timer = self.set_interval(1 / 12, self._advance)
        self._advance()

    def pause_animation(self) -> None:
        if self._animation_timer is not None:
            self._animation_timer.pause()

    def _advance(self) -> None:
        self._phase = (self._phase + 0.025) % 1.0
        self._tick += 1
        state = self.STATES[(self._tick // 36) % len(self.STATES)]
        frame = build_dot_sphere(
            width=SPHERE_FRAME_WIDTH,
            height=SPHERE_FRAME_HEIGHT,
            phase=self._phase,
            state_key=state,
        )
        self.update(render_dot_sphere_text(frame))


class CortistrateDemoApp(App[None]):
    """Fullscreen first-run demo cockpit."""

    TITLE = "Cortistrate Memory Core"
    SUB_TITLE = "dot sphere demo"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "replay", "Replay"),
    ]

    CSS = f"""
    Screen {{
        background: {CORTISTRATE_BLACK};
        color: {CORTISTRATE_INK};
    }}

    #shell {{
        width: 100%;
        height: 100%;
        padding: 1 2;
        border: round {CORTISTRATE_BORDER};
    }}

    #command-strip {{
        height: 2;
        padding: 0 1;
        color: {CORTISTRATE_INK};
        content-align: left middle;
    }}

    #main {{
        height: 1fr;
        margin-top: 1;
    }}

    #memory-field {{
        width: 1fr;
        border: round {CORTISTRATE_AMBER};
        background: {CORTISTRATE_SURFACE};
        padding: 0 2;
    }}

    #field-header {{
        height: 2;
        content-align: left middle;
    }}

    #field-answer {{
        height: 2;
        border-top: hkey {CORTISTRATE_AMBER_DIM};
        background: {CORTISTRATE_SURFACE_RAISED};
        padding: 0 1;
    }}

    #signal-rail {{
        width: 48;
        height: 100%;
        margin-left: 1;
        border: round {CORTISTRATE_AMBER};
        background: {CORTISTRATE_SURFACE};
        padding: 1 2;
    }}

    #provenance-strip {{
        height: 6;
        margin-top: 1;
    }}

    #source-lock {{
        width: 1fr;
        border: round {CORTISTRATE_CYAN};
        background: {CORTISTRATE_SURFACE};
        padding: 0 2;
        margin-right: 1;
    }}

    #recall-lock {{
        width: 54;
        border: round {CORTISTRATE_GREEN};
        background: {CORTISTRATE_SURFACE};
        padding: 0 2;
    }}

    #payoff {{
        height: 2;
        border-top: hkey {CORTISTRATE_YELLOW};
        background: {CORTISTRATE_SURFACE};
        color: {CORTISTRATE_INK};
        padding: 0 1;
        margin-top: 1;
        content-align: left middle;
    }}

    Footer {{
        background: {CORTISTRATE_BLACK};
        color: {CORTISTRATE_MUTED};
    }}

    FooterKey {{
        background: {CORTISTRATE_BLACK};
    }}

    FooterKey > .footer-key--key {{
        color: {CORTISTRATE_BLACK};
        background: {CORTISTRATE_YELLOW};
        text-style: bold;
    }}

    FooterKey > .footer-key--description {{
        color: {CORTISTRATE_INK};
        background: {CORTISTRATE_BLACK};
    }}
    """

    def __init__(self, *, story: DemoStory | None = None) -> None:
        super().__init__()
        self._story = story or default_demo_story()

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Static(_hero_text(), id="command-strip")
            with Horizontal(id="main"):
                memory_field = Vertical(id="memory-field")
                memory_field.border_title = "memory field"
                with memory_field:
                    yield Static(_field_header_text(self._story), id="field-header")
                    yield DotSphereWidget()
                    yield Static(_sphere_caption(self._story), id="field-answer")
                signal_rail = Static(_signal_rail_text(self._story), id="signal-rail")
                signal_rail.border_title = "signal rail"
                yield signal_rail
            with Horizontal(id="provenance-strip"):
                source_lock = Static(_source_tree_text(self._story), id="source-lock")
                source_lock.border_title = "source lock"
                yield source_lock
                recall_lock = Static(_recall_proof_text(self._story), id="recall-lock")
                recall_lock.border_title = "recall lock"
                yield recall_lock
            yield Static(_payoff_text(self._story), id="payoff")
            yield Footer(show_command_palette=False)

    def action_replay(self) -> None:
        widget = self.query_one(DotSphereWidget)
        widget._tick = 0
        widget._phase = 0.0
        widget._advance()


def run_demo_tui(*, story: DemoStory | None = None) -> None:
    CortistrateDemoApp(story=story).run()


def _hero_text() -> Text:
    return Text.assemble(
        (" cortistrate demo ", f"bold black on {CORTISTRATE_YELLOW}"),
        ("  memory core ", f"bold {CORTISTRATE_YELLOW}"),
        ("online", CORTISTRATE_MUTED),
    )


def _field_header_text(story: DemoStory | None = None) -> Text:
    story = story or default_demo_story()
    return Text.assemble(
        (f"user={story.owner}", f"bold {CORTISTRATE_INK}"),
        ("  scope=permissive", f"bold {CORTISTRATE_YELLOW_SOFT}"),
        ("  trace ", CORTISTRATE_MUTED),
        ("conversation -> facts -> index", f"bold {CORTISTRATE_YELLOW}"),
        ("  live", f"bold {CORTISTRATE_ORANGE}"),
    )


def _sphere_caption(story: DemoStory | None = None) -> Text:
    story = story or default_demo_story()
    return Text.assemble(
        ("query  ", f"bold {CORTISTRATE_CYAN}"),
        (f"{story.query}  ", CORTISTRATE_INK),
        ("->  ", CORTISTRATE_MUTED),
        ("answer ", f"bold {CORTISTRATE_GREEN}"),
        (story.answer, f"bold {CORTISTRATE_GREEN}"),
    )


def _signal_rail_text(story: DemoStory | None = None) -> Text:
    story = story or default_demo_story()
    return Text.assemble(
        ("● ", f"bold {CORTISTRATE_GREEN}"),
        ("memory core        ", CORTISTRATE_INK),
        ("ready\n", f"bold {CORTISTRATE_GREEN}"),
        ("● ", f"bold {CORTISTRATE_YELLOW_SOFT}"),
        ("conversation       ", CORTISTRATE_INK),
        ("captured\n", f"bold {CORTISTRATE_YELLOW_SOFT}"),
        ("● ", f"bold {CORTISTRATE_ORANGE}"),
        ("episode -> facts   ", CORTISTRATE_INK),
        ("live\n", f"bold {CORTISTRATE_ORANGE}"),
        ("● ", f"bold {CORTISTRATE_CYAN}"),
        ("SQLite + Postgres   ", CORTISTRATE_INK),
        ("synced\n", f"bold {CORTISTRATE_CYAN}"),
        ("● ", f"bold {CORTISTRATE_GREEN}"),
        ("memory recall      ", CORTISTRATE_INK),
        ("hit\n", f"bold {CORTISTRATE_GREEN}"),
        ("\nsource route\n", CORTISTRATE_MUTED),
        (_rail_cell(story.source_filename), CORTISTRATE_INK),
        (" attached\n", f"bold {CORTISTRATE_YELLOW_SOFT}"),
        (_rail_cell(story.fact_filename), CORTISTRATE_INK),
        (" 7 nodes\n", f"bold {CORTISTRATE_ORANGE}"),
        ("postgres orbit      ", CORTISTRATE_INK),
        ("synced\n", f"bold {CORTISTRATE_CYAN}"),
        ("\nrecall proof\n", CORTISTRATE_MUTED),
        ("score              ", CORTISTRATE_INK),
        ("0.628\n", f"bold {CORTISTRATE_GREEN}"),
        ("source             ", CORTISTRATE_INK),
        (f"{story.source_filename}\n", f"bold {CORTISTRATE_CYAN}"),
        ("field integrity\n", CORTISTRATE_MUTED),
        ("█████████░  92%\n", f"bold {CORTISTRATE_YELLOW}"),
        ("latency            ", CORTISTRATE_MUTED),
        ("42 ms\n", f"bold {CORTISTRATE_GREEN}"),
        ("mode               ", CORTISTRATE_MUTED),
        ("permissive", f"bold {CORTISTRATE_INK}"),
    )


def _rail_cell(value: str, *, width: int = SIGNAL_RAIL_SOURCE_WIDTH) -> str:
    if len(value) > width:
        return f"{value[: width - 3]}..."
    return f"{value:<{width}}"


def _source_tree_text(story: DemoStory | None = None) -> Text:
    story = story or default_demo_story()
    return Text.assemble(
        ("episode ", CORTISTRATE_MUTED),
        (f"{story.source_filename}\n", f"bold {CORTISTRATE_YELLOW_SOFT}"),
        ("facts   ", CORTISTRATE_MUTED),
        (f"{story.fact_filename}\n", f"bold {CORTISTRATE_ORANGE}"),
        ("index   ", CORTISTRATE_MUTED),
        ("sqlite/system.db + postgres/tables\n", CORTISTRATE_CYAN),
        ("root    ", CORTISTRATE_MUTED),
        ("~/.cortistrate/default_app/default_project", CORTISTRATE_INK),
    )


def _recall_proof_text(story: DemoStory | None = None) -> Text:
    story = story or default_demo_story()
    return Text.assemble(
        ("score   ", CORTISTRATE_MUTED),
        ("0.628\n", f"bold {CORTISTRATE_GREEN}"),
        ("scope   ", CORTISTRATE_MUTED),
        (f"user={story.owner} project=default\n", CORTISTRATE_INK),
        ("answer  ", CORTISTRATE_MUTED),
        (story.answer, f"bold {CORTISTRATE_YELLOW}"),
    )


def _payoff_text(story: DemoStory | None = None) -> Text:
    story = story or default_demo_story()
    return Text.assemble(
        ("memory formed: ", f"bold {CORTISTRATE_YELLOW}"),
        (
            f"Cortistrate recalled {story.answer} and kept the source attached.",
            f"bold {CORTISTRATE_INK}",
        ),
    )
