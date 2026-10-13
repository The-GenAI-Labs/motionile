const DIRECTIVE_PATTERNS = [/^\s*eslint-disable-next-line\s+\S+/u, /^\s*@ts-expect-error\s+\S+/u];
const TRIPLE_SLASH_REFERENCE = /^\/\s*<reference\s+(path|types|lib)=["'][^"']+["']\s*\/>\s*$/u;

const isAllowedDirective = (comment) => {
  if (comment.type === "Shebang") {
    return true;
  }
  if (comment.type === "Line" && TRIPLE_SLASH_REFERENCE.test(comment.value)) {
    return true;
  }
  const value = comment.type === "Block" ? comment.value.trim() : comment.value;
  return DIRECTIVE_PATTERNS.some((pattern) => pattern.test(value));
};

const noComments = {
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow comments except eslint-disable-next-line, @ts-expect-error and triple-slash references",
    },
    schema: [],
    messages: {
      forbidden:
        "Comments are not allowed. Express intent through names and structure. Only eslint-disable-next-line <rule>, @ts-expect-error <reason> and triple-slash references are permitted.",
    },
  },
  create(context) {
    return {
      Program() {
        for (const comment of context.sourceCode.getAllComments()) {
          if (!isAllowedDirective(comment)) {
            context.report({ loc: comment.loc, messageId: "forbidden" });
          }
        }
      },
    };
  },
};

export default noComments;
