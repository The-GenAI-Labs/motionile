const config = {
  printWidth: 100,
  semi: true,
  singleQuote: false,
  trailingComma: "all",
  bracketSpacing: true,
  arrowParens: "always",
  endOfLine: "lf",
  overrides: [
    {
      files: ["*.md"],
      options: { proseWrap: "preserve" },
    },
  ],
};

export default config;
