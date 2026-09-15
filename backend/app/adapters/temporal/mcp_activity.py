"""Temporal activity boundary for MCP tool calls through the sole-egress gateway."""

from __future__ import annotations

from typing import Any

from temporalio import activity

from app.adapters.auth_workload import JWTWorkloadTokenIssuer
from app.adapters.mcp.gateway_client import GatewayMCPClient
from app.domain.mcp import ToolCall

__all__ = ["MCP_TOOL_ACTIVITY", "MCPToolActivities"]

MCP_TOOL_ACTIVITY = "invoke_mcp_tool"


class MCPToolActivities:
    def __init__(self, endpoint: str, issuer: JWTWorkloadTokenIssuer) -> None:
        self._endpoint = endpoint
        self._issuer = issuer

    @activity.defn(name=MCP_TOOL_ACTIVITY)
    async def invoke(self, raw: dict[str, Any]) -> dict[str, Any]:
        call = ToolCall.model_validate(raw)
        token = self._issuer.issue(subject=call.context.workload_subject)
        result = await GatewayMCPClient(self._endpoint, token).invoke(call)
        return result.model_dump(mode="json")
