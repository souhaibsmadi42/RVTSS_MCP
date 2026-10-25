# -*- coding: utf-8 -*-
"""batch_execute: several RVTSS edits in ONE Revit transaction group (one undo step, all or nothing).

Each sub-command is a normal RVTSS tool call ({tool, arguments}). It is validated
and turned into its Revit payload by the real tool function, with the HTTP call
captured instead of sent (tools/_common.BATCH_CAPTURE). The captured payloads go
to Revit in one /batch/ request, where revit_mcp/batch.py runs them inside a
TransactionGroup: Assimilate() on success, RollBack() on the first failure
(unless continue_on_error) or for dry_run.
"""
import json
from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ._compat import Context, MODIFIES
from ._common import BATCH_CAPTURE, compact, post_confirmable, DOC_HELP

MAX_COMMANDS = 20

# Tools whose Revit work is ONE POST on the active/target project and that open
# their own transaction (so a TransactionGroup can merge them). Arbitrary code,
# document/file lifecycle, family documents and file exports are excluded.
BATCHABLE = (
    "set_parameters", "bulk_update_parameter", "transform_elements", "delete_elements", "create_elements",
    "manage_element_types", "create_view", "view_graphics", "manage_sheets", "create_schedule", "batch_rename",
    "manage_groups", "global_parameters", "map_parameters", "tag_elements", "create_text_notes",
    "manage_materials", "manage_view_filters", "manage_revisions", "manage_worksets",
)


class BatchCommand(BaseModel):
    tool: str = Field(description="RVTSS tool name, e.g. 'set_parameters' (see the batchable list)")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="That tool's arguments")


def register_batch_tools(mcp, revit_get, revit_post, server=None):
    """server: the underlying MCP server, used to validate sub-commands through its tool manager."""

    @mcp.tool(annotations=MODIFIES)
    async def batch_execute(
        commands: Annotated[List[BatchCommand], Field(min_length=1, max_length=MAX_COMMANDS)],
        continue_on_error: Annotated[bool, Field(description="Keep going after a failed command (its own "
                                                             "transaction is still rolled back)")] = False,
        dry_run: Annotated[bool, Field(description="Run everything, report, then roll the whole group back")] = False,
        name: Annotated[Optional[str], Field(description="Undo-step name shown in Revit")] = None,
        document: Annotated[Optional[str], Field(description=DOC_HELP)] = None,
        ctx: Context = None,
    ) -> str:
        """Run up to 20 RVTSS edits as ONE Revit undo step: all succeed or everything is rolled back.

        Batchable tools: set_parameters, bulk_update_parameter, transform_elements, delete_elements,
        create_elements, manage_element_types, create_view, view_graphics, manage_sheets, create_schedule,
        batch_rename, manage_groups, global_parameters, map_parameters, tag_elements, create_text_notes,
        manage_materials, manage_view_filters, manage_revisions, manage_worksets.

        Example - type change plus marks, one undo step:
            commands=[{tool: "manage_element_types", arguments: {action: "change_type", element_ids: [1,2],
                       type_id: 345}}, {tool: "set_parameters", arguments: {element_ids: [1,2],
                       parameter: "Mark", value: "D-01"}}]
        Rules: per-command dry_run is ignored (use the batch dry_run); a command that answers with a
        confirmation preview needs confirm=true in its own arguments; ids created by an earlier command
        are not known yet when the batch is built - create first, then batch the follow-up edits.
        Every sub-result is reported with its index; rolled_back=true means nothing was kept.
        """
        if server is None:
            return _error("batch_execute is not available: the server was registered without a tool manager.")
        manager = getattr(server, "_tool_manager", None)
        payloads, errors = [], []
        for i, cmd in enumerate(commands):
            if cmd.tool not in BATCHABLE:
                errors.append({"index": i, "tool": cmd.tool, "error": "not batchable",
                               "hint": "Batchable: " + ", ".join(BATCHABLE)})
                continue
            args = dict(cmd.arguments)
            args.pop("dry_run", None)
            if document is not None:
                args.setdefault("document", document)
            sink = []
            token = BATCH_CAPTURE.set(sink)
            try:
                await manager.call_tool(cmd.tool, args, ctx)
            except Exception as e:  # argument validation (ToolError) or tool-side refusal
                errors.append({"index": i, "tool": cmd.tool, "error": str(e)})
                continue
            finally:
                BATCH_CAPTURE.reset(token)
            if len(sink) != 1:
                errors.append({"index": i, "tool": cmd.tool,
                               "error": "expected exactly one Revit call, the tool made %d" % len(sink)})
                continue
            endpoint, data = sink[0]
            data.pop("dry_run", None)
            payloads.append({"index": i, "tool": cmd.tool, "endpoint": endpoint, "payload": data})
        if errors:
            return _error("No command was sent to Revit: %d of %d commands are invalid." % (len(errors), len(commands)),
                          invalid_commands=errors)
        data = compact(commands=payloads, continue_on_error=continue_on_error or None, dry_run=dry_run or None,
                       name=name, document=document)
        return await post_confirmable(revit_post, "/batch/", data, ctx, 600.0, "batch_execute")


def _error(message, **extra):
    out = {"status": "error", "error": message}
    out.update(extra)
    return json.dumps(out, indent=2, default=str)
