// Общие типы занятий.
export interface MediaDto {
  id: string;
  media_type: string;
  mime_type: string;
  description: string;
}

export interface TaskDto {
  item_id: string;
  task_type: string;
  direction: string;
  card_id: string;
  content_version: number;
  position: number;
  status: string;
  draft_version: number;
  question_text: string | null;
  question_context: string | null;
  hint: string | null;
  language: string | null;
  media_question: MediaDto[];
  media_answer: MediaDto[];
  choices: string[] | null;
  statement?: string | null;
  match_lefts?: Array<{ id: string; text: string }>;
  match_rights?: Array<{ id: string; text: string }>;
  tts_text?: string;
  match_right_text?: string;
}

export interface SessionDto {
  id: string;
  mode: string;
  status: string;
  settings: Record<string, unknown>;
  current_index: number;
  active_ms: number;
  deadline_at: string | null;
  started_at: string;
  item_count: number;
  tasks?: TaskDto[];
}

export interface Feedback {
  correct: boolean;
  correct_text?: string;
  explanation?: string;
  example?: string;
  answer_context?: string;
  possible_typo?: boolean;
  assisted?: boolean;
  replayed?: boolean;
  answer_id?: string;
  mastered?: boolean;
  round_failed?: boolean;
  statement?: string | null;
  pair_results?: Array<{ left: string; correct: boolean }>;
  pairs?: Array<{ left: string; right: string }>;
}
