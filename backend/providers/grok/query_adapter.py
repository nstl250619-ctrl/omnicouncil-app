"""Grok query adapter — send/wait/extract for grok.com.

Minimal adapter: inherits BaseQueryAdapter, only overrides config().
All page interaction is config-driven via PlatformConfig.page.
"""

from __future__ import annotations

from providers.base.query_adapter import BaseQueryAdapter, QueryAdapterConfig


class GrokQueryAdapter(BaseQueryAdapter):

    def config(self) -> QueryAdapterConfig:
        return QueryAdapterConfig(
            platform="grok",
            display_name="Grok",
            home_url="https://grok.com",
            icon_color="#64748b",
            icon_emoji="🤖",
        )
