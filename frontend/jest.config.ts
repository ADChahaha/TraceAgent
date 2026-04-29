import nextJest from "next/jest.js";

const createJestConfig = nextJest({
  dir: "./"
});

const jestConfig = {
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  testEnvironment: "jsdom",
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1"
  }
};

export default createJestConfig(jestConfig);
