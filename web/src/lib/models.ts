import type { Models, OpenRouterList, OpenRouterModel } from "./types";

// A model as the list of models to choose from shows it
export interface ModelRow {
  id: string;
  provider: string;
  // What OpenRouter calls it, which the rest are not given
  name: string | null;
  // Whether the keys its provider needs are set
  ready: boolean;
  // What it costs and how much it reads, as a short phrase each, where they are known
  price: string | null;
  context: string | null;
}

const OPENROUTER = "OpenRouter";

function dollars(amount: number): string {
  return amount > 0 && amount < 0.01 ? "<$0.01" : `$${Number(amount.toFixed(2))}`;
}

// What a model of OpenRouter's costs, in a phrase: "Free", "$3 in, $15 out per million tokens", or none where the price
// depends on what is asked, as a router's does
export function describePrice(model: Pick<OpenRouterModel, "input_per_million" | "output_per_million">): string | null {
  const { input_per_million: input, output_per_million: output } = model;
  if (input === null || output === null) return null;
  if (input === 0 && output === 0) return "Free";

  return `${dollars(input)} in, ${dollars(output)} out per million tokens`;
}

export function describeContext(tokens: number | null): string | null {
  if (tokens === null || tokens <= 0) return null;
  if (tokens >= 1_000_000) return `${Number((tokens / 1_000_000).toFixed(1))}M tokens`;

  return `${Math.round(tokens / 1000)}k tokens`;
}

// The models to choose from: those of each provider the server lists, in its order, and in the place of the few of
// OpenRouter's it lists, all of OpenRouter's once they are known
export function rowsOf(models: Models | null, openrouter: OpenRouterList | null): ModelRow[] {
  const listed = models?.models ?? [];
  const known = (openrouter?.models.length ?? 0) > 0;
  const ready = listed.find((choice) => choice.provider === OPENROUTER)?.ready ?? false;
  const rows: ModelRow[] = [];
  let placed = false;
  const addAllOfOpenRouter = () => {
    placed = true;
    for (const model of openrouter?.models ?? []) {
      rows.push({
        id: model.id,
        provider: OPENROUTER,
        name: model.name,
        ready,
        price: describePrice(model),
        context: describeContext(model.context_length),
      });
    }
  };

  for (const choice of listed) {
    if (choice.provider === OPENROUTER && known) {
      if (!placed) addAllOfOpenRouter();
      continue;
    }
    rows.push({
      id: choice.id,
      provider: choice.provider ?? "Others",
      name: null,
      ready: choice.ready,
      price: null,
      context: null,
    });
  }
  if (known && !placed) addAllOfOpenRouter();

  return rows;
}

// The models whose names, or what OpenRouter calls them, have every word of what was typed in them, whatever the case
export function matching(rows: ModelRow[], query: string): ModelRow[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);

  return words.length === 0
    ? rows
    : rows.filter((row) => {
        const text = `${row.id} ${row.name ?? ""}`.toLowerCase();

        return words.every((word) => text.includes(word));
      });
}

// What to offer to use as it is typed, which is a model that is not in the list: the server says whether it can be used.
// None where nothing is typed or it is the name of one that is listed.
export function typedModel(rows: ModelRow[], query: string): string | null {
  const typed = query.trim();

  return typed === "" || rows.some((row) => row.id === typed) ? null : typed;
}

// The rows grouped by whose they are, in the order they come
export function grouped(rows: ModelRow[]): [string, ModelRow[]][] {
  const groups = new Map<string, ModelRow[]>();
  for (const row of rows) groups.set(row.provider, [...(groups.get(row.provider) ?? []), row]);

  return [...groups];
}
