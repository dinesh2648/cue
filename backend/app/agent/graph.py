"""A minimal, LangGraph-compatible async StateGraph.

This mirrors the subset of the `langgraph.graph.StateGraph` API the copilot uses
(add_node / add_edge / add_conditional_edges / set_entry_point / compile →
ainvoke), so the pipeline can be lifted onto the real `langgraph` package with no
node-code changes. Keeping it in-repo means the app runs with zero extra deps.

State is a plain dict; each node returns a partial dict that is merged in
(LangGraph's default reducer behaviour).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

START = "__start__"
END = "__end__"

Node = Callable[[dict], Awaitable[dict]]
Router = Callable[[dict], str]


class StateGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, str] = {}
        self._cond: dict[str, tuple[Router, dict[str, str]]] = {}
        self._entry: str | None = None

    def add_node(self, name: str, fn: Node) -> "StateGraph":
        self._nodes[name] = fn
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        self._edges[src] = dst
        return self

    def add_conditional_edges(
        self, src: str, router: Router, mapping: dict[str, str]
    ) -> "StateGraph":
        self._cond[src] = (router, mapping)
        return self

    def set_entry_point(self, name: str) -> "StateGraph":
        self._entry = name
        return self

    def compile(self) -> "CompiledGraph":
        if self._entry is None:
            raise ValueError("entry point not set")
        return CompiledGraph(self._nodes, self._edges, self._cond, self._entry)


class CompiledGraph:
    def __init__(
        self,
        nodes: dict[str, Node],
        edges: dict[str, str],
        cond: dict[str, tuple[Router, dict[str, str]]],
        entry: str,
    ) -> None:
        self._nodes = nodes
        self._edges = edges
        self._cond = cond
        self._entry = entry

    def _next(self, current: str, state: dict) -> str:
        if current in self._cond:
            router, mapping = self._cond[current]
            return mapping.get(router(state), END)
        return self._edges.get(current, END)

    async def ainvoke(self, state: dict) -> dict:
        current = self._entry
        steps = 0
        trace: list[str] = []
        while current != END:
            if steps > 64:  # cycle guard
                break
            node = self._nodes[current]
            update = await node(state)
            if update:
                state.update(update)
            trace.append(current)
            current = self._next(current, state)
            steps += 1
        state["_trace"] = trace
        return state
