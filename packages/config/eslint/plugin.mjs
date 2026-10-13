import noComments from "./rules/no-comments.mjs";

const motionilePlugin = {
  meta: { name: "@motionile/eslint-plugin" },
  rules: {
    "no-comments": noComments,
  },
};

export default motionilePlugin;
