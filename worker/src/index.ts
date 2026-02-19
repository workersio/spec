import { nanoid } from "nanoid";

export interface Env {
  DB: D1Database;
}

const MAX_CONTENT_SIZE = 1024 * 1024; // 1 MB

const CORS_HEADERS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

// --- Helpers ---

function json(data: unknown, status = 200): Response {
  return Response.json(data, { status, headers: CORS_HEADERS });
}

/** Parse YAML frontmatter from spec content. Matches Rust spec_parser.rs logic. */
function parseSpec(content: string): { title: string; description: string } {
  const trimmed = content.trimStart();
  if (!trimmed.startsWith("---")) {
    return { title: "", description: "" };
  }

  const afterFirst = trimmed.slice(3).replace(/^[\r\n]+/, "");
  const endIdx = afterFirst.indexOf("\n---");
  if (endIdx === -1) {
    return { title: "", description: "" };
  }

  const frontmatter = afterFirst.slice(0, endIdx);
  let title = "";
  let name = "";
  let description = "";

  for (const rawLine of frontmatter.split("\n")) {
    const line = rawLine.trim();
    const titleVal = stripYamlField(line, "title");
    if (titleVal !== null) {
      title = titleVal;
      continue;
    }
    const nameVal = stripYamlField(line, "name");
    if (nameVal !== null) {
      name = nameVal;
      continue;
    }
    const descVal = stripYamlField(line, "description");
    if (descVal !== null) {
      description = descVal;
    }
  }

  return { title: title || name, description };
}

/** Extract value from a YAML field line like `title: "Some Title"` or `title: Some Title`. */
function stripYamlField(line: string, field: string): string | null {
  const prefix = `${field}:`;
  if (!line.startsWith(prefix)) {
    return null;
  }
  let val = line.slice(prefix.length).trim();
  if (val.startsWith('"') && val.endsWith('"')) {
    val = val.slice(1, -1);
  }
  return val;
}

/** Count numbered list items (e.g. "1. First step"). Matches Rust count_steps logic. */
function countSteps(content: string): number {
  return content.split("\n").filter((l) => {
    const t = l.trim();
    return t.length > 2 && /^\d/.test(t) && t.includes(". ");
  }).length;
}

// --- Worker ---

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const { pathname } = url;

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    // GET /health
    if (request.method === "GET" && pathname === "/health") {
      return json({ status: "ok" });
    }

    // POST /api/specs
    if (request.method === "POST" && pathname === "/api/specs") {
      let body: { content?: string; version?: string };
      try {
        body = await request.json();
      } catch {
        return json({ error: "Invalid JSON" }, 400);
      }

      const content = body.content ?? "";
      if (!content) {
        return json({ error: "content must not be empty" }, 400);
      }
      if (content.length > MAX_CONTENT_SIZE) {
        return json(
          { error: `content exceeds maximum size of ${MAX_CONTENT_SIZE} bytes` },
          413
        );
      }

      const { title, description } = parseSpec(content);
      const id = nanoid(21);
      const stepCount = countSteps(content);
      const version = body.version ?? "";

      try {
        await env.DB.prepare(
          "INSERT INTO specs (id, content, title, summary, step_count, version) VALUES (?, ?, ?, ?, ?, ?)"
        )
          .bind(id, content, title, description, stepCount, version)
          .run();
      } catch {
        return json({ error: "Failed to store spec" }, 500);
      }

      const specUrl = `${url.origin}/s/${id}`;
      return json({ id, url: specUrl }, 201);
    }

    // GET /api/specs/:id
    const specMatch = pathname.match(/^\/api\/specs\/([A-Za-z0-9_-]+)$/);
    if (request.method === "GET" && specMatch) {
      const id = specMatch[1];
      let row;
      try {
        row = await env.DB.prepare(
          "SELECT id, content, title, summary, step_count, version, created_at FROM specs WHERE id = ?"
        )
          .bind(id)
          .first();
      } catch {
        return json({ error: "Database error" }, 500);
      }

      if (!row) {
        return json({ error: "spec not found" }, 404);
      }
      return json(row);
    }

    return json({ error: "not found" }, 404);
  },
} satisfies ExportedHandler<Env>;
