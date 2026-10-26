"""All the tools the assistant may call: the handbook's and the campaign's own."""

from apps.ai.services import campaign_tools, handbook_tools

TOOLS = [*handbook_tools.TOOLS, *campaign_tools.TOOLS]


def runner(user, campaign):
    """`run_tool(name, arguments) -> (text, ui)` for `gateway.converse`, bound to one user and
    campaign (so the campaign tools only reach what that user may see)."""

    def run(name: str, arguments: dict):
        if campaign_tools.handles(name):
            return campaign_tools.run_ui(user, campaign, name, arguments)
        return handbook_tools.run_ui(name, arguments)

    return run
