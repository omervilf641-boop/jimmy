# -*- coding: utf-8 -*-
"""Model Context Protocol client for Jarvis.

Every tool Jarvis had until now was hand-written here. MCP is the standard
protocol for tool servers, so this lets him borrow whole toolsets the community
already maintains — filesystem, git, databases, web fetch — instead of us
writing each one.

Servers are declared in mcp.json next to this file:

    {
      "servers": {
        "files": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/me/Documents"]
        }
      }
    }

Each server runs in its own thread with its own asyncio loop, because the MCP
SDK is async while the rest of Jarvis is a plain threaded HTTP server.
"""
import asyncio
import json
import os
import threading

CONFIG_NAME = "mcp.json"
CALL_TIMEOUT = 60


def _resolve_command(command, env):
    """Find the real executable for a command like "npx".

    Launched from Electron, the server inherits a trimmed PATH that often has
    no Node in it, and the subprocess dies with a bare "cannot find the file".
    """
    import shutil

    found = shutil.which(command, path=env.get("PATH"))
    if found:
        return found

    candidates = []
    if command in ("npx", "npm", "node"):
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramW6432", r"C:\Program Files"),
                     os.path.join(os.environ.get("APPDATA", ""), "npm")):
            for ext in (".cmd", ".exe", ""):
                candidates.append(os.path.join(root, "nodejs", command + ext))
                candidates.append(os.path.join(root, command + ext))
    for path in candidates:
        if path and os.path.isfile(path):
            # keep Node on PATH for anything the server spawns in turn
            env["PATH"] = os.path.dirname(path) + os.pathsep + env.get("PATH", "")
            return path
    return command      # let it fail with the original name


def _describe(exc):
    """Flatten an ExceptionGroup — anyio wraps the real cause inside one, and
    "unhandled errors in a TaskGroup" on its own says nothing useful."""
    inner = getattr(exc, "exceptions", None)
    if inner:
        return " | ".join(_describe(e) for e in inner)
    return f"{type(exc).__name__}: {exc}"


class MCPServer:
    """One MCP server: its own thread, loop, and long-lived session."""

    def __init__(self, name, spec):
        self.name = name
        self.spec = spec
        self.tools = []          # tool schemas as reported by the server
        self.error = None
        self.ready = threading.Event()
        self._loop = None
        self._session = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        # MCP servers are subprocesses, and on Windows only a Proactor loop can
        # spawn them. A plain new_event_loop() in a worker thread failed with
        # "unhandled errors in a TaskGroup" — this is that bug.
        if os.name == "nt" and hasattr(asyncio, "ProactorEventLoop"):
            self._loop = asyncio.ProactorEventLoop()
        else:
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except BaseException as e:
            self.error = _describe(e)
            self.ready.set()

    async def _serve(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = dict(os.environ)
        env.update(self.spec.get("env") or {})
        params = StdioServerParameters(
            command=_resolve_command(self.spec["command"], env),
            args=self.spec.get("args", []),
            env=env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self._session = session
                listed = await session.list_tools()
                # The SDK renamed this field between versions: older builds
                # expose inputSchema, current ones input_schema.
                def schema_of(tool):
                    return (getattr(tool, "input_schema", None)
                            or getattr(tool, "inputSchema", None)
                            or {"type": "object", "properties": {}})

                self.tools = [
                    {
                        "name": t.name,
                        "description": (t.description or "")[:400],
                        "schema": schema_of(t),
                    }
                    for t in listed.tools
                ]
                self.ready.set()
                # hold the connection open for the life of the process
                while True:
                    await asyncio.sleep(3600)

    def call(self, tool_name, arguments):
        """Call a tool on this server from a non-async thread."""
        if self.error:
            return {"error": f"{self.name}: {self.error}"}
        if not self._session:
            return {"error": f"{self.name} is not connected"}

        async def _invoke():
            result = await self._session.call_tool(tool_name, arguments or {})
            parts = []
            for item in result.content:
                text = getattr(item, "text", None)
                parts.append(text if text is not None else str(item))
            return "\n".join(parts).strip()

        future = asyncio.run_coroutine_threadsafe(_invoke(), self._loop)
        try:
            return {"result": future.result(timeout=CALL_TIMEOUT)}
        except Exception as e:
            return {"error": f"{tool_name} failed: {e}"}


class MCPRegistry:
    """All configured servers, and the flat tool namespace they expose."""

    def __init__(self, base_dir):
        self.path = os.path.join(base_dir, CONFIG_NAME)
        self.servers = {}
        self._index = {}          # exposed tool name -> (server, real tool name)

    def start(self):
        config = self._read_config()
        for name, spec in (config.get("servers") or {}).items():
            if spec.get("disabled") or not spec.get("command"):
                continue
            self.servers[name] = MCPServer(name, spec)

        for name, server in self.servers.items():
            server.ready.wait(timeout=25)     # npx may need to fetch the package
            for tool in server.tools:
                # namespaced so two servers can both offer "read_file"
                self._index[f"{name}__{tool['name']}"] = (server, tool["name"])
        return self.status()

    def _read_config(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except ValueError as e:
            return {"_error": f"mcp.json is not valid JSON: {e}"}

    def tool_definitions(self):
        """Tool schemas in the shape the chat model expects."""
        defs = []
        for exposed, (server, real) in self._index.items():
            spec = next((t for t in server.tools if t["name"] == real), None)
            if not spec:
                continue
            defs.append({
                "type": "function",
                "function": {
                    "name": exposed,
                    "description": f"[{server.name}] {spec['description']}",
                    "parameters": spec["schema"],
                },
            })
        return defs

    def has(self, name):
        return name in self._index

    def call(self, name, arguments):
        entry = self._index.get(name)
        if not entry:
            return {"error": f"unknown MCP tool: {name}"}
        server, real = entry
        return server.call(real, arguments)

    def status(self):
        return {
            "servers": [
                {
                    "name": name,
                    "tools": len(s.tools),
                    "error": s.error,
                }
                for name, s in self.servers.items()
            ],
            "total_tools": len(self._index),
        }
