"""
Registry mapping platform name -> adapter class.
Pass this dict straight into DeployAgent(adapters=...).
"""

from .vercel import VercelAdapter
from .netlify import NetlifyAdapter
from .huggingface import HuggingFaceAdapter
from .gce import GCEAdapter
from .gcp import GCPAdapter
from .supabase import SupabaseAdapter

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
