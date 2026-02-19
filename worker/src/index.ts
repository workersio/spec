import { Hono } from "hono";
import { cors } from "hono/cors";
import { nanoid } from "nanoid";

type Bindings = {
  DB: D1Database;
};

const app = new Hono<{ Bindings: Bindings }>();

const MAX_CONTENT_SIZE = 1024 * 1024; // 1 MB

// --- Middleware ---

app.use("*", cors());

// --- Helpers ---

/** Parse YAML frontmatter from spec content. */
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

/** Count numbered list items (e.g. "1. First step"). */
function countSteps(content: string): number {
  return content.split("\n").filter((l) => {
    const t = l.trim();
    return t.length > 2 && /^\d/.test(t) && t.includes(". ");
  }).length;
}

// --- Routes ---

app.get("/health", (c) => {
  return c.json({ status: "ok" });
});

app.post("/api/specs", async (c) => {
  const body = await c.req.json<{ content?: string; version?: string }>();

  const content = body.content ?? "";
  if (!content) {
    return c.json({ error: "content must not be empty" }, 400);
  }
  if (content.length > MAX_CONTENT_SIZE) {
    return c.json(
      { error: `content exceeds maximum size of ${MAX_CONTENT_SIZE} bytes` },
      413
    );
  }

  const { title, description } = parseSpec(content);
  const id = nanoid(21);
  const stepCount = countSteps(content);
  const version = body.version ?? "";

  await c.env.DB.prepare(
    "INSERT INTO specs (id, content, title, summary, step_count, version) VALUES (?, ?, ?, ?, ?, ?)"
  )
    .bind(id, content, title, description, stepCount, version)
    .run();

  const specUrl = `${new URL(c.req.url).origin}/s/${id}`;
  return c.json({ id, url: specUrl }, 201);
});

app.get("/s/:id", async (c) => {
  const id = c.req.param("id");
  const row = await c.env.DB.prepare("SELECT content FROM specs WHERE id = ?")
    .bind(id)
    .first<{ content: string }>();

  if (!row) {
    return c.text("Not found\n", 404);
  }

  c.header("Content-Type", "text/markdown; charset=utf-8");
  return c.body(row.content);
});

app.get("/api/specs/:id", async (c) => {
  const id = c.req.param("id");
  const row = await c.env.DB.prepare(
    "SELECT id, content, title, summary, step_count, version, created_at FROM specs WHERE id = ?"
  )
    .bind(id)
    .first();

  if (!row) {
    return c.json({ error: "spec not found" }, 404);
  }

  return c.json(row);
});

// --- Global error handler ---

app.onError((err, c) => {
  if (err instanceof SyntaxError) {
    return c.json({ error: "Invalid JSON" }, 400);
  }
  console.error(err);
  return c.json({ error: "Internal server error" }, 500);
});

export default app;
