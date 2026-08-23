---
related_files:
  - src/lingtai/kernel/tool_plugin/CONTRACT.md
  - src/lingtai/kernel/tool_plugin/BEHAVIORS.md
  - src/lingtai/kernel/tool_plugin/__init__.py
  - src/lingtai/kernel/ANATOMY.md
  - src/lingtai/adapters/tool_plugin_host.py
  - src/lingtai/kernel/base_agent/ANATOMY.md
  - src/lingtai/kernel/base_agent/tools.py
  - src/lingtai/kernel/base_agent/__init__.py
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/mcp/ANATOMY.md
  - src/lingtai/tools/mcp/__init__.py
  - src/lingtai/tools/mcp/manual/SKILL.md
  - src/lingtai/tools/notification/ANATOMY.md
  - src/lingtai/tools/notification/__init__.py
  - src/lingtai/tools/notification/manual/SKILL.md
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/_manual.py
  - src/lingtai/agent.py
  - tests/test_tool_plugin_declaration.py
maintenance: |
  Keep this Anatomy reciprocal with CONTRACT.md and BEHAVIORS.md. Update the
  Port, production adapter, both declared slices, compact vertical tests, and
  related paths together when an official family or port changes. Code is the
  structural source of truth; report mismatches instead of normalizing them.
---
# Declared Host Tool Plugin Anatomy

`src/lingtai/kernel/tool_plugin/` is the Core shape and registrar for official
model-facing tool families. It owns no family behavior, plugin discovery,
transport, or Agent argument. Two live declarations use it today: `mcp` and
`notification`.

## Components

- `__init__.py` owns `ToolPluginDeclaration`, `BoundToolPlugin`, the
  least-privilege `ToolPluginHost`, `register_official_tool_plugins`, the
  one-use authorized mount transaction, typed errors, and the static official
  name/host-port tuples. `MANUAL_ACTION` is appended by declarations; families
  cannot declare it as an operational action.
- The host Protocols are `WorkdirPort`, `PromptSectionPort`,
  `NotificationStatePort`, and host-only `ToolMountPort`. The grantable set is
  intentionally only `workdir`, `prompt_section`, and `notification_state`.
  The third exists solely because the notification vertical slice consumes it.
- `adapters/tool_plugin_host.py` owns production implementations. Workdir and
  prompt adapters hold one read/write callback each. `AgentNotificationStateAdapter`
  holds only callbacks bound to Notification Core functions; it exposes no
  Agent, Store, delivery fingerprint, producer state, or mount capability.
- `tools/mcp/__init__.py` declares `mcp`, requiring `workdir` and
  `prompt_section`; its activation reconciles prompt presentation.
- `tools/notification/__init__.py` declares `notification`, requiring
  `workdir` and `notification_state`; it composes public LTP children and
  delegates all actual notification state operations through that port.

## Connections

1. A family constructs `DECLARATION` at module import. Validation checks the
   operational action tuple, exact schema keys, reserved manual exclusion,
   nonempty identity fields, callable binder, and earned port names before an
   Agent exists.
2. The ordinary capability boot loop calls the family's `setup(agent)`. The
   composition adapter builds the full port table for that agent and calls the
   kernel registrar with the declaration, mount seam, live claim view, and
   claim/binding authorization callbacks.
3. The registrar first checks every batch name against
   `OFFICIAL_TOOL_PLUGIN_NAMES`, duplicate batch names, and the live claim map.
   Only then does it grant exactly the named port subset, bind, run optional
   activation, issue a transaction, mount it, and record the claim.
4. `BaseAgent._mount_official_tool` verifies transaction provenance, anchored
   declaration, and exact bound result before its common `_add_tool` boundary
   publishes the schema/handler. Generic mounts cannot claim reserved names.
5. `ToolPluginDeclaration.bind` checks that the bound schema advertises exactly
   `public_actions`, preventing a family from declaring and shipping different
   model-facing action inventories.

## Notification state boundary

The notification adapter binds these Core-owned operations to the real Agent:
whole/event/ref mirror dismissal with `invoked_by="notification"`, consumer
channel delay, hook add/drop/edit/list, and bounded action logging. The declared
family sees those operations as `NotificationStatePort` methods. It cannot
construct a local Store helper or bypass producer guards; dismissal therefore
keeps Core's delivered-version comparison, protected-channel refusal,
producer-specific generic-dismiss guards, post-molt acknowledgement, and all
real state signaling. Delay and hook operations likewise preserve the existing
Core timer, Store lock, allowlist mirror, and producer separation.

## State and ordering

- `OFFICIAL_TOOL_PLUGIN_NAMES` is a static kernel-owned tuple, not discovery.
- `BaseAgent._official_tool_plugins` is the live per-agent claim map. Persistent
  declaration anchors survive refresh; bound results rebuild with the live tool
  surface. Re-registering the same declaration object is idempotent.
- Name checking is all-or-nothing before any bind/activation/mount. Later
  bind/port/activation/mount failures propagate after earlier members may have
  mounted; this component owns no unmount capability.
- The host facade contains only its granted port mapping. There is no component
  cache, manifest, process, or family-local runtime state.

## Tests

`tests/test_tool_plugin_declaration.py` is the compact live proof for both
slices. It checks controlled claim/mount, unchanged MCP dispatch, and
notification's package manual, check placeholder, and Core-backed dismissal.
Family behavior remains in the focused MCP and notification suites. Architecture
document validation checks this diagram's related-file graph.
