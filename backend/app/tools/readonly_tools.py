"""Read-only, always-auto tools: fact gathering with no side effects."""
from __future__ import annotations

from app.core.constants import ToolMode
from app.schemas.tool import ToolResult
from app.tools.base import Tool, ToolContext


class SearchKBTool(Tool):
    name = "search_kb"
    mode = ToolMode.AUTO
    description = (
        "Search the internal knowledge base for documented fixes. Returns articles with "
        "their ids, steps and a match confidence. Use the returned kb_ids when you cite a fix."
    )

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."},
                "category": {"type": ["string", "null"], "description": "Optional category filter."},
            },
            "required": ["query"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        result = await ctx.kb_service.search(args["query"], category=args.get("category"))
        ctx.retrieved_ids |= result.cited_ids()
        return ToolResult(
            content={
                "no_good_match": result.no_good_match,
                "confidence": result.confidence,
                "hits": [
                    {
                        "kb_id": h.article_id,
                        "title": h.title,
                        "risk_level": h.risk_level,
                        "score": h.score,
                        "required_tools": h.required_tools,
                        "steps": h.steps,
                    }
                    for h in result.hits
                ],
            }
        )


class CheckAccountStatusTool(Tool):
    name = "check_account_status"
    mode = ToolMode.AUTO
    description = "Look up a user's account status (enabled, locked, MFA, password expiry)."

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "username": {"type": ["string", "null"], "description": "UPN; defaults to requester."}
            },
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        subject = args.get("username") or ctx.ticket.requester_upn
        status = await ctx.backends.identity.get_account_status(subject)
        return ToolResult(content=status)


class RunEndpointDiagnosticTool(Tool):
    name = "run_endpoint_diagnostic"
    mode = ToolMode.AUTO
    description = (
        "Run a read-only diagnostic on the user's device. check is one of: "
        "vpn, connectivity, disk, general."
    )

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "asset_id": {"type": ["string", "null"]},
                "check": {
                    "type": "string",
                    "enum": ["vpn", "connectivity", "disk", "general"],
                },
            },
            "required": ["check"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        asset_id = args.get("asset_id") or (ctx.ticket.entities or {}).get("asset_id") or "primary-device"
        result = await ctx.backends.endpoint.run_diagnostic(asset_id, args.get("check", "general"))
        return ToolResult(content=result)
