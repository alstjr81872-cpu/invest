export type Json = Record<string, any>;
export interface Instrument {
  id: string;
  ticker: string;
  name: string;
  exchange: string;
  sector: string;
  currency: string;
}
export interface Quote {
  last: number;
  bid: number | null;
  ask: number | null;
  source: string;
  observed_at: string;
  collected_at: string;
  available_at: string;
  quality: Json;
  sequence: number;
}
export interface Candidate extends Instrument {
  status: string;
  score: number | null;
  probability: string;
  reasons: string[];
  risks: string[];
  price: number;
  as_of: string;
  source: string;
  strategy: string;
  strategy_version: string;
  holding_days: number;
  entry: number;
  stop: number;
  target: number;
  risk: Json;
  indicators: Json;
  components: Json;
  relative_market: number;
  relative_sector: number;
  rules: Json;
  evidence: string;
}
export interface Research {
  id: string;
  created_at: string;
  expires_at: string;
  candidates: Candidate[];
  shortlist: string[];
  market: Json;
  settings: Preferences;
  mode: string;
  news_state: string;
  disclosures_state: string;
  minute_bars: string;
}
export interface Preferences {
  holding_days: number;
  target_pct: number;
  budget: number;
  currency: "USD" | "KRW";
  loss_budget_usd: number;
  max_weight: number;
  max_positions: number;
  existing_holdings: { instrument_id: string; quantity: number }[];
  budget_usd?: number;
}
export interface Position extends Instrument {
  quantity: number;
  average_price: number;
  entry_fees: number;
  opened_at: string;
  version: number;
  original: Json;
  quote: Quote | null;
  usable: boolean;
  data_state: string;
  valuation: Json | null;
}
export interface Portfolio {
  cash: number;
  available_cash: number;
  reserved: number;
  initial_cash: number;
  equity: number;
  unrealized_pnl: number;
  realized_pnl: number;
  positions: Position[];
  mode: string;
  valuation_complete: boolean;
  version: number;
}
export interface Order {
  id: string;
  instrument_id: string;
  side: "buy" | "sell";
  status: string;
  quantity: number;
  filled: number;
  average_price: number;
  displayed_price: number;
  limit_price: number;
  fees: number;
  created_at: string;
  mode: string;
  context: Json;
}
export interface Job {
  id: string;
  kind: string;
  state: string;
  payload: Json;
  result: Json | null;
  created_at: string;
  completed_at: string | null;
}
