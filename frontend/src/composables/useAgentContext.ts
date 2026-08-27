export type AgentPageContext = {
  route?: string;
  profile?: string;
  locale?: string;
  product_id?: string;
  phase?: string;
  csv_path?: string;
  iap_path?: string;
  screenshots_path?: string;
  fields?: Record<string, string>;
};

/** Editor/create overrides only. Profile and default paths are collected at request time. */
let overrides: AgentPageContext = {};

function cloneContext(ctx: AgentPageContext): AgentPageContext {
  return {
    ...ctx,
    fields: ctx.fields ? { ...ctx.fields } : undefined,
  };
}

export function setAgentPageContext(partial: AgentPageContext): void {
  overrides = {
    ...overrides,
    ...partial,
    fields:
      partial.fields || overrides.fields
        ? { ...(overrides.fields || {}), ...(partial.fields || {}) }
        : undefined,
  };
}

export function clearAgentPageContext(): void {
  overrides = {};
}

export function currentAgentPageContext(): AgentPageContext {
  return cloneContext(overrides);
}

export function useAgentContext() {
  return {
    setAgentPageContext,
    clearAgentPageContext,
    currentAgentPageContext,
  };
}
