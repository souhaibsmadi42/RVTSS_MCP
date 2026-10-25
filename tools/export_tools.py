# -*- coding: utf-8 -*-
"""RVTSS v2.2 export tools (files written by Revit on the Revit machine)."""
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import Field

from ._compat import Context, READ_ONLY, MODIFIES
from ._common import compact, post, call_with_progress, DOC_HELP
from .utils import format_response

Doc = Annotated[Optional[str], Field(description=DOC_HELP)]


def register_export_tools(mcp, revit_get, revit_post):

    @mcp.tool(annotations=READ_ONLY)
    async def list_export_settings(document: Doc = None, ctx: Context = None) -> str:
        """Export options available in this model: DWG setups, PDF settings, sheet sets, IFC versions, NWC exporter."""
        return await post(revit_post, "/export/settings/", compact(document=document), ctx)

    @mcp.tool(annotations=MODIFIES)
    async def export_documents(
        format: Literal["pdf", "dwg", "dxf", "ifc", "nwc", "csv"],
        sheets: Annotated[Optional[List[Union[str, int]]], Field(description="Sheet numbers or ids")] = None,
        views: Annotated[Optional[List[Union[str, int]]], Field(description="View names or ids (csv: schedules)")] = None,
        view_set: Annotated[Optional[str], Field(description="Saved view/sheet set name")] = None,
        all_sheets: bool = False,
        folder: Annotated[Optional[str], Field(description="Absolute folder on the Revit machine")] = None,
        naming: Annotated[Optional[str], Field(description="File name template: {number} {name} {revision} "
                                                           "{view_type} {date} {document}")] = None,
        file_name: Annotated[Optional[str], Field(description="ifc / nwc / combined pdf: file name")] = None,
        combine: Annotated[bool, Field(description="pdf: one combined file")] = False,
        setup: Annotated[Optional[str], Field(description="Saved DWG export setup or PDF export setting name")] = None,
        pdf_color: Optional[Literal["color", "grayscale", "black_line"]] = None,
        ifc_version: Annotated[Optional[str], Field(description="e.g. IFC2x3CV2, IFC4RV (list_export_settings)")] = None,
        ifc_view: Annotated[Optional[str], Field(description="ifc: export only what this view shows")] = None,
        ifc_options: Annotated[Optional[Dict[str, Any]], Field(description="ifc: exporter options by name")] = None,
        nwc_view: Annotated[Optional[str], Field(description="nwc: export only this view (default whole model)")] = None,
        delimiter: Annotated[Optional[str], Field(description="csv: field delimiter (default ',')")] = None,
        overwrite: bool = False,
        dry_run: Annotated[bool, Field(description="Resolve targets and file names only")] = False,
        document: Doc = None,
        ctx: Context = None,
    ) -> str:
        """Export sheets / views to PDF, DWG or DXF, the model to IFC or NWC, schedules to CSV.

        Default folder: ~/Documents/RVTSS/exports/<model> on the Revit machine. ifc_options passes IFC
        exporter options by name, e.g. {ExportBaseQuantities: true}.
        One file per sheet / view named from `naming` (default '{number} - {name}' for sheets),
        or one combined PDF. Existing files are kept unless overwrite=true. Run dry_run=true first to
        see the exact file list. PDF needs Revit 2022+; NWC needs Autodesk's NWC exporter add-in.
        """
        data = compact(format=format, sheets=sheets, views=views, view_set=view_set, all_sheets=all_sheets or None,
                       folder=folder, naming=naming, file_name=file_name, combine=combine or None, setup=setup,
                       pdf_color=pdf_color, ifc_version=ifc_version, ifc_view=ifc_view, ifc_options=ifc_options,
                       nwc_view=nwc_view, delimiter=delimiter, overwrite=overwrite or None, dry_run=dry_run or None,
                       document=document)
        response = await call_with_progress(revit_post, "/export/run/", data, ctx, 1800.0, "Export " + format)
        return format_response(response)
