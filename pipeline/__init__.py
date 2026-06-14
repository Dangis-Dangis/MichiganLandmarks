"""Michigan Landmarks data pipeline.

Aggregates open datasets (Michigan DNR markers + state parks, NRHP points, Wikidata
lighthouses, NPS units) into one unified schema and emits app-ready outputs plus a
data report. Run with: python -m pipeline.run
"""

__version__ = "0.1.0"
