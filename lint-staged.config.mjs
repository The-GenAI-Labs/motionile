const quote = (files) => files.map((file) => JSON.stringify(file)).join(" ");

const checkComments = (files) =>
  `uv run --project apps/server python scripts/check_no_comments.py ${quote(files)}`;

const config = {
  "*.{ts,tsx,js,mjs,cjs}": (files) => [
    `eslint --max-warnings=0 --no-warn-ignored --fix ${quote(files)}`,
    `prettier --write ${quote(files)}`,
  ],
  "*.py": (files) => [
    `uv run --project apps/server ruff check --fix --force-exclude ${quote(files)}`,
    `uv run --project apps/server ruff format --force-exclude ${quote(files)}`,
    checkComments(files),
  ],
  "*.{json,md}": (files) => {
    const formatted = files.filter((file) => !file.includes("/evals/cassettes/"));
    return formatted.length > 0 ? `prettier --write ${quote(formatted)}` : [];
  },
  "*.{yml,yaml,css}": (files) => [`prettier --write ${quote(files)}`, checkComments(files)],
  "{*.toml,*.sh,*.tf,*.tftpl,*.hcl,*.lua,**/Dockerfile,**/Caddyfile,.husky/*,**/.env.example}": (
    files,
  ) => checkComments(files),
};

export default config;
