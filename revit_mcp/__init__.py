# -*- coding: UTF-8 -*-
"""
MCP Module for Revit Integration
Contains all MCP route handlers organized by functionality
"""

__version__ = "0.1.0"
__author__ = "Juan D. Rodriguez, Jean-Marc Couffin"
# RVTSS upgrade (Suhaib Al Smadi): version of the RVTSS route modules
RVTSS_VERSION = "2.3.0"

# module name -> error message for route modules that failed to register
# (filled by startup.py, reported by /status/)
REGISTRATION_ERRORS = {}

# Common imports that all modules might need
import logging

# Make logger available to all submodules
logger = logging.getLogger(__name__)