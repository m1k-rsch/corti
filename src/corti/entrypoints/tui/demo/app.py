"""Textual TUI for ``corti demo``."""

from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Footer, Static

from corti.entrypoints.tui.demo.data import DemoStory, default_demo_story
from corti.entrypoints.tui.demo.widgets.sphere import (
    CORTI_AMBER,
    CORTI_AMBER_DIM,
    CORTI_CYAN,
    CORTI_GREEN,
    CORTI_ORANGE,
    CORTI_YELLOW,
    CORTI_YELLOW_SOFT,
    build_dot_sphere,
    render_dot_sphere_text,
)

CORTI_BLACK = "#1D1C18"
CORTI_SURFACE = "#24231E"
CORTI_SURFACE_RAISED = "#31302B"
CORTI_INK = "#F5EDDC"
CORTI_MUTED = "#918C80"
CORTI_BORDER = "#5A5549"
SPHERE_FRAME_WIDTH = 37
SPHERE_FRAME_HEIGHT = 17
TERMINAL_CELL_HEIGHT_RATIO = 2.0
SIGNAL_RAIL_SOURCE_WIDTH = 18


class DotSphereWidget(Static):
    """Animated dot sphere that represents Corti memory activity."""

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


class CortiDemoApp(App[None]):
    """Fullscreen first-run demo cockpit."""

    TITLE = "Corti Memory Core"
    SUB_TITLE = "dot sphere demo"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "replay", "Replay"),
    ]

    CSS = f"""
    Screen {{
        background: {CORTI_BLACK};
        color: {CORTI_INK};
    }}

    #shell {{
        width: 100%;
        height: 100%;
        padding: 1 2;
        border: round {CORTI_BORDER};
    }}

    #command-strip {{
        height: 2;
        padding: 0 1;
        color: {CORTI_INK};
        content-align: left middle;
    }}

    #main {{
        height: 1fr;
        margin-top: 1;
    }}

    #memory-field {{
        width: 1fr;
        border: round {CORTI_AMBER};
        background: {CORTI_SURFACE};
        padding: 0 2;
    }}

    #field-header {{
        height: 2;
        content-align: left middle;
    }}

    #field-answer {{
        height: 2;
        border-top: hkey {CORTI_AMBER_DIM};
        background: {CORTI_SURFACE_RAISED};
        padding: 0 1;
    }}

    #signal-rail {{
        width: 48;
        height: 100%;
        margin-left: 1;
        border: round {CORTI_AMBER};
        background: {CORTI_SURFACE};
        padding: 1 2;
    }}

    #provenance-strip {{
        height: 6;
        margin-top: 1;
    }}

    #source-lock {{
        width: 1fr;
        border: round {CORTI_CYAN};
        background: {CORTI_SURFACE};
        padding: 0 2;
        margin-right: 1;
    }}

    #recall-lock {{
        width: 54;
        border: round {CORTI_GREEN};
        background: {CORTI_SURFACE};
        padding: 0 2;
    }}

    #payoff {{
        height: 2;
        border-top: hkey {CORTI_YELLOW};
        background: {CORTI_SURFACE};
        color: {CORTI_INK};
        padding: 0 1;
        margin-top: 1;
        content-align: left middle;
    }}

    Footer {{
        background: {CORTI_BLACK};
        color: {CORTI_MUTED};
    }}

    FooterKey {{
        background: {CORTI_BLACK};
    }}

    FooterKey > .footer-key--key {{
        color: {CORTI_BLACK};
        background: {CORTI_YELLOW};
        text-style: bold;
    }}

    FooterKey > .footer-key--description {{
        color: {CORTI_INK};
        background: {CORTI_BLACK};
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
    CortiDemoApp(story=story).run()


def _hero_text() -> Text:
    return Text.assemble(
        (" corti demo ", f"bold black on {CORTI_YELLOW}"),
        ("  memory core ", f"bold {CORTI_YELLOW}"),
        ("online", CORTI_MUTED),
    )


def _field_header_text(story: DemoStory | None = None) -> Text:
    story = story or default_demo_story()
    return Text.assemble(
        (f"user={story.owner}", f"bold {CORTI_INK}"),
        ("  scope=permissive", f"bold {CORTI_YELLOW_SOFT}"),
        ("  trace ", CORTI_MUTED),
        ("conversation -> facts -> index", f"bold {CORTI_YELLOW}"),
        ("  live", f"bold {CORTI_ORANGE}"),
    )


def _sphere_caption(story: DemoStory | None = None) -> Text:
    story = story or default_demo_story()
    return Text.assemble(
        ("query  ", f"bold {CORTI_CYAN}"),
        (f"{story.query}  ", CORTI_INK),
        ("->  ", CORTI_MUTED),
        ("answer ", f"bold {CORTI_GREEN}"),
        (story.answer, f"bold {CORTI_GREEN}"),
    )


def _signal_rail_text(story: DemoStory | None = None) -> Text:
    story = story or default_demo_story()
    return Text.assemble(
        ("● ", f"bold {CORTI_GREEN}"),
        ("memory core        ", CORTI_INK),
        ("ready\n", f"bold {CORTI_GREEN}"),
        ("● ", f"bold {CORTI_YELLOW_SOFT}"),
        ("conversation       ", CORTI_INK),
        ("captured\n", f"bold {CORTI_YELLOW_SOFT}"),
        ("● ", f"bold {CORTI_ORANGE}"),
        ("episode -> facts   ", CORTI_INK),
        ("live\n", f"bold {CORTI_ORANGE}"),
        ("● ", f"bold {CORTI_CYAN}"),
        ("SQLite + Postgres   ", CORTI_INK),
        ("synced\n", f"bold {CORTI_CYAN}"),
        ("● ", f"bold {CORTI_GREEN}"),
        ("memory recall      ", CORTI_INK),
        ("hit\n", f"bold {CORTI_GREEN}"),
        ("\nsource route\n", CORTI_MUTED),
        (_rail_cell(story.source_filename), CORTI_INK),
        (" attached\n", f"bold {CORTI_YELLOW_SOFT}"),
        (_rail_cell(story.fact_filename), CORTI_INK),
        (" 7 nodes\n", f"bold {CORTI_ORANGE}"),
        ("postgres orbit      ", CORTI_INK),
        ("synced\n", f"bold {CORTI_CYAN}"),
        ("\nrecall proof\n", CORTI_MUTED),
        ("score              ", CORTI_INK),
        ("0.628\n", f"bold {CORTI_GREEN}"),
        ("source             ", CORTI_INK),
        (f"{story.source_filename}\n", f"bold {CORTI_CYAN}"),
        ("field integrity\n", CORTI_MUTED),
        ("█████████░  92%\n", f"bold {CORTI_YELLOW}"),
        ("latency            ", CORTI_MUTED),
        ("42 ms\n", f"bold {CORTI_GREEN}"),
        ("mode               ", CORTI_MUTED),
        ("permissive", f"bold {CORTI_INK}"),
    )


def _rail_cell(value: str, *, width: int = SIGNAL_RAIL_SOURCE_WIDTH) -> str:
    if len(value) > width:
        return f"{value[: width - 3]}..."
    return f"{value:<{width}}"


def _source_tree_text(story: DemoStory | None = None) -> Text:
    story = story or default_demo_story()
    return Text.assemble(
        ("episode ", CORTI_MUTED),
        (f"{story.source_filename}\n", f"bold {CORTI_YELLOW_SOFT}"),
        ("facts   ", CORTI_MUTED),
        (f"{story.fact_filename}\n", f"bold {CORTI_ORANGE}"),
        ("index   ", CORTI_MUTED),
        ("sqlite/system.db + postgres/tables\n", CORTI_CYAN),
        ("root    ", CORTI_MUTED),
        ("~/.corti/default_app/default_project", CORTI_INK),
    )


def _recall_proof_text(story: DemoStory | None = None) -> Text:
    story = story or default_demo_story()
    return Text.assemble(
        ("score   ", CORTI_MUTED),
        ("0.628\n", f"bold {CORTI_GREEN}"),
        ("scope   ", CORTI_MUTED),
        (f"user={story.owner} project=default\n", CORTI_INK),
        ("answer  ", CORTI_MUTED),
        (story.answer, f"bold {CORTI_YELLOW}"),
    )


def _payoff_text(story: DemoStory | None = None) -> Text:
    story = story or default_demo_story()
    return Text.assemble(
        ("memory formed: ", f"bold {CORTI_YELLOW}"),
        (
            f"Corti recalled {story.answer} and kept the source attached.",
            f"bold {CORTI_INK}",
        ),
    )
