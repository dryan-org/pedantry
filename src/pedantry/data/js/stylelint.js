/** @type {import("stylelint").Config} */
const config = {
  extends: ["stylelint-config-standard", "stylelint-config-recess-order"],
  rules: {
    "declaration-no-important": true,
    "font-weight-notation": "numeric",
    "custom-property-pattern": [
      "^(__?)?([a-z][a-z0-9]*)(-[a-z0-9]+)*$",
      {
        message:
          "Expected custom property name to be kebab-case, optionally prefixed with __ or _",
      },
    ],
    // Allow :host and ::slotted for Web Components
    "selector-pseudo-class-no-unknown": [
      true,
      {
        ignorePseudoClasses: ["host", "host-context"],
      },
    ],
    "selector-pseudo-element-no-unknown": [
      true,
      {
        ignorePseudoElements: ["slotted", "part"],
      },
    ],
    // Allow @property for CSS custom properties
    "at-rule-no-unknown": [
      true,
      {
        ignoreAtRules: ["property"],
      },
    ],
  },
};

export default config;
