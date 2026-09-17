// Typed client for the local backend, with errors turned into messages a student can act on.

import { AnswerResponse, CheckRequest, CheckResponse, ConceptMap, Material } from "./types";

export class ApiError extends Error {
  constructor(message: string, readonly status: number | null) {
    super(message);
  }
}

type Fetch = typeof fetch;

export class ApiClient {
  constructor(private readonly baseUrl: string, private readonly fetchImpl: Fetch = fetch) {}

  startCheck(request: CheckRequest): Promise<CheckResponse> {
    return this.json("POST", "/checks", request);
  }

  getCheck(sessionId: string): Promise<CheckResponse> {
    return this.json("GET", `/checks/${encodeURIComponent(sessionId)}`);
  }

  submitAnswer(sessionId: string, gapIndex: number, answer: string): Promise<AnswerResponse> {
    return this.json("POST", `/checks/${encodeURIComponent(sessionId)}/answers`, { gap_index: gapIndex, answer });
  }

  materials(sessionId: string, gapIndex: number): Promise<Material[]> {
    return this.json("GET", `/checks/${encodeURIComponent(sessionId)}/gaps/${gapIndex}/materials`);
  }

  conceptMap(studentId: string): Promise<ConceptMap> {
    return this.json("GET", `/learners/${encodeURIComponent(studentId)}/mastery`);
  }

  /** A backend-relative thumbnail URL as a data: URI, so the webview needs no network access. */
  async thumbnailDataUri(thumbnailUrl: string): Promise<string | null> {
    try {
      const response = await this.fetchImpl(this.url(thumbnailUrl));
      if (!response.ok) {
        return null;
      }
      const bytes = Buffer.from(await response.arrayBuffer());
      return `data:image/png;base64,${bytes.toString("base64")}`;
    } catch {
      return null;
    }
  }

  private url(path: string): string {
    return this.baseUrl.replace(/\/+$/, "") + path;
  }

  private async json<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    let response: Response;
    try {
      response = await this.fetchImpl(this.url(path), {
        method,
        headers: body === undefined ? undefined : { "content-type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(
        `Can't reach the Lab Assistant backend at ${this.baseUrl}. Start it with "uv run labassistant-api".`,
        null,
      );
    }
    if (response.ok) {
      return (await response.json()) as T;
    }
    throw new ApiError(await friendlyMessage(response), response.status);
  }
}

export async function friendlyMessage(response: Response): Promise<string> {
  let detail = "";
  try {
    const data = (await response.json()) as { detail?: unknown };
    detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? "");
  } catch {
    detail = response.statusText;
  }
  switch (response.status) {
    case 413:
      return "The project is too large to send. Try a smaller folder or add large files to .gitignore.";
    case 422:
      return `Lab Assistant can't check this selection: ${detail}`;
    case 409:
      return `That action isn't possible right now: ${detail}`;
    case 502:
      return `The AI gave an answer Lab Assistant couldn't use. Please try again. (${detail})`;
    case 503:
      return `The AI service is unavailable: ${detail}`;
    default:
      return `Lab Assistant backend error (${response.status}): ${detail}`;
  }
}
