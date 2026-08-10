"""
Registry mapping platform name -> adapter class.
Pass this dict straight into DeployAgent(adapters=...).
"""

from .gce import GCEAdapter
from .gcp import GCPAdapter
from .huggingface import HuggingFaceAdapter
from .netlify import NetlifyAdapter
from .supabase import SupabaseAdapter
from .vercel import VercelAdapter

ADAPTER_REGISTRY = {
    VercelAdapter.platform: VercelAdapter,
    NetlifyAdapter.platform: NetlifyAdapter,
    HuggingFaceAdapter.platform: HuggingFaceAdapter,
    GCEAdapter.platform: GCEAdapter,
    GCPAdapter.platform: GCPAdapter,
    SupabaseAdapter.platform: SupabaseAdapter,
}

__all__ = [
    "ADAPTER_REGISTRY",
    "VercelAdapter",
    "NetlifyAdapter",
    "HuggingFaceAdapter",
    "GCEAdapter",
    "GCPAdapter",
    "SupabaseAdapter",
]
