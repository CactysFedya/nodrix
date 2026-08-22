from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .errors import RuntimeGraphError
from .manifest import (
    external_transport_bindings,
)
from .session import SessionContext
from .integration import ApplicationContext, ResourceContext

try:
    from ._native_queue import BoundedQueue as _NativeBoundedQueue
except Exception:  # pragma: no cover
    _NativeBoundedQueue = None


from .runtime_components import (
    LoadedApplication,
    LoadedResource,
    LoadedSession,
    _AsyncBridge,
)


class IntegrationRuntimeMixin:
    def _resource_instance(self, name: str) -> Any:
        session = self.sessions.get(name)
        if session is not None:
            return session.instance
        resource = self.resources.get(name)
        if resource is not None:
            return resource.instance
        raise RuntimeGraphError(f"Unknown runtime resource binding {name!r}")

    @staticmethod
    def _managed_resource_health(loaded: LoadedResource) -> dict[str, Any]:
        health = getattr(loaded.instance, "health", None)
        if not callable(health):
            return {"status": "ok", "open": loaded.opened}
        try:
            return dict(health() or {})
        except Exception as exc:
            return {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }

    @staticmethod
    def _application_health(loaded: LoadedApplication) -> dict[str, Any]:
        health = getattr(loaded.instance, "health", None)
        if not callable(health):
            return {
                "status": "ok" if loaded.started else "stopped",
                "running": loaded.started,
            }
        try:
            value = dict(health() or {})
        except Exception as exc:
            return {
                "status": "error",
                "running": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        if loaded.completed:
            value["status"] = "completed"
            value["running"] = False
        else:
            value["running"] = bool(
                value.get("running", True) and loaded.started
            )
        return value

    def _open_resources(self, run_dir: Path) -> None:
        bridge = _AsyncBridge()
        opened: list[LoadedResource] = []
        try:
            for loaded in self.resources.values():
                opener = getattr(loaded.instance, "open", None)
                if callable(opener):
                    bridge.resolve(
                        opener(
                            ResourceContext(
                                name=loaded.name,
                                run_dir=run_dir,
                                project_dir=self.base_dir,
                                runtime_mode=self.manifest.runtime.mode,
                                environment=self.execution_environment,
                                bindings={
                                    binding: self.sessions[session_name].instance
                                    for binding, session_name in loaded.binding.bindings.items()
                                },
                            )
                        )
                    )
                loaded.opened = True
                opened.append(loaded)
                self._emit_event(
                    "resource_ready",
                    resource=loaded.name,
                    uses=loaded.uses,
                    health=self._managed_resource_health(loaded),
                )
        except BaseException:
            for loaded in reversed(opened):
                closer = getattr(loaded.instance, "close", None)
                if callable(closer):
                    try:
                        bridge.resolve(closer())
                    except Exception:
                        pass
                loaded.opened = False
            raise
        finally:
            bridge.close()

    def _close_resources(self) -> None:
        bridge = _AsyncBridge()
        try:
            for loaded in reversed(tuple(self.resources.values())):
                if not loaded.opened:
                    continue
                closer = getattr(loaded.instance, "close", None)
                try:
                    if callable(closer):
                        bridge.resolve(closer())
                    self._emit_event(
                        "resource_stopped",
                        resource=loaded.name,
                        uses=loaded.uses,
                    )
                except BaseException as exc:
                    self._record_error(loaded.name, exc)
                finally:
                    loaded.opened = False
        finally:
            bridge.close()

    def _start_applications(self, run_dir: Path) -> None:
        bridge = _AsyncBridge()
        configured: list[LoadedApplication] = []
        try:
            for loaded in self.applications.values():
                # Include the current application in rollback even when its
                # configure() method fails after acquiring partial state.
                configured.append(loaded)
                context = ApplicationContext(
                    name=loaded.name,
                    run_dir=run_dir,
                    project_dir=self.base_dir,
                    runtime_mode=self.manifest.runtime.mode,
                    environment=self.execution_environment,
                    bindings={
                        binding: self._resource_instance(resource_name)
                        for binding, resource_name in loaded.binding.resource_bindings.items()
                    },
                    external_links=tuple(
                        link
                        for link in external_transport_bindings(self.manifest)
                        if str(link["from"]).split(".", 1)[0] == loaded.name
                        or str(link["to"]).split(".", 1)[0] == loaded.name
                    ),
                )
                bridge.resolve(loaded.instance.configure(context))
                loaded.configured = True
                bridge.resolve(loaded.instance.start())
                loaded.started = True
                self._emit_event(
                    "application_started",
                    application=loaded.name,
                    uses=loaded.uses,
                    health=self._application_health(loaded),
                )
        except BaseException:
            for loaded in reversed(configured):
                try:
                    bridge.resolve(loaded.instance.stop())
                except Exception:
                    pass
                loaded.started = False
                loaded.configured = False
            raise
        finally:
            bridge.close()

    def _applications_active(self) -> bool:
        active = False
        bridge = _AsyncBridge()
        try:
            for loaded in self.applications.values():
                if not loaded.started or loaded.completed:
                    continue
                poller = getattr(loaded.instance, "poll", None)
                try:
                    result = bridge.resolve(poller()) if callable(poller) else None
                    state = (
                        dict(result)
                        if isinstance(result, Mapping)
                        else self._application_health(loaded)
                    )
                    status = str(state.get("status", "ok")).lower()
                    running = bool(state.get("running", True))
                    if status in {"error", "failed", "unhealthy"}:
                        raise RuntimeError(
                            str(state.get("error") or f"application status is {status}")
                        )
                    if running:
                        active = True
                        continue
                    loaded.completed = True
                    loaded.started = False
                    self._emit_event(
                        "application_completed",
                        application=loaded.name,
                        uses=loaded.uses,
                        health=state,
                    )
                except BaseException as exc:
                    self._record_error(loaded.name, exc)
                    return False
        finally:
            bridge.close()
        return active

    def _stop_applications(self) -> None:
        bridge = _AsyncBridge()
        try:
            for loaded in reversed(tuple(self.applications.values())):
                if not loaded.configured:
                    continue
                try:
                    bridge.resolve(loaded.instance.stop())
                    self._emit_event(
                        "application_stopped",
                        application=loaded.name,
                        uses=loaded.uses,
                    )
                except BaseException as exc:
                    self._record_error(loaded.name, exc)
                finally:
                    loaded.started = False
                    loaded.configured = False
        finally:
            bridge.close()

    @staticmethod
    def _session_health(loaded: LoadedSession) -> dict[str, Any]:
        health = getattr(loaded.instance, "health", None)
        if not callable(health):
            return {"status": "ok", "open": loaded.opened}
        try:
            return dict(health() or {})
        except Exception as exc:
            return {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _open_sessions(self, run_dir: Path) -> None:
        bridge = _AsyncBridge()
        opened: list[LoadedSession] = []
        try:
            for loaded in self.sessions.values():
                opener = getattr(loaded.instance, "open", None)
                if callable(opener):
                    bridge.resolve(
                        opener(
                            SessionContext(
                                name=loaded.name,
                                run_dir=run_dir,
                                project_dir=self.base_dir,
                                runtime_mode=self.manifest.runtime.mode,
                                environment=self.execution_environment,
                            )
                        )
                    )
                loaded.opened = True
                opened.append(loaded)
                self._emit_event(
                    "session_ready",
                    session=loaded.name,
                    uses=loaded.uses,
                    health=self._session_health(loaded),
                )
        except BaseException:
            for loaded in reversed(opened):
                closer = getattr(loaded.instance, "close", None)
                if callable(closer):
                    try:
                        bridge.resolve(closer())
                    except Exception:
                        pass
                loaded.opened = False
            raise
        finally:
            bridge.close()

    def _close_sessions(self) -> None:
        bridge = _AsyncBridge()
        try:
            for loaded in reversed(tuple(self.sessions.values())):
                if not loaded.opened:
                    continue
                closer = getattr(loaded.instance, "close", None)
                try:
                    if callable(closer):
                        bridge.resolve(closer())
                    self._emit_event(
                        "session_stopped",
                        session=loaded.name,
                        uses=loaded.uses,
                    )
                except BaseException as exc:
                    self._record_error(loaded.name, exc)
                finally:
                    loaded.opened = False
        finally:
            bridge.close()
