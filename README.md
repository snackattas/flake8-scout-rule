# Flake8 Scout Rule

![sample usage](https://github.com/user-attachments/assets/93e0c654-0138-4bc2-81cb-9cefe10ceec9)

> The Scout Rule: Leave Your Code Better Than You Found It

We all strive to be good digital citizens, right? The Scout Rule is a simple idea: **always leave your code cleaner than you found it.**

But let's face it, dealing with legacy code can be a real pain. It might not follow best practices or have linting rules in place.

**Introducing the Flake8 Scout Rule!**

This handy tool is like a digital cleanup crew. It works in two steps:

1. **Finds the Mess**: It runs `flake8` to identify all the coding mistakes.
2. **Adds a Note**: It politely adds a `# noqa: <codes>` comment next to each issue, basically saying, "Hey, future developer, this code needs some love."

**Why Use It?**

* **Gentle Introduction to New Linting Rules**: It doesn't force you to fix everything at once.
* **Teamwork Makes the Dream Work**: Your team can gradually clean up the code together.
* **Easy to Use**: No need to manually annotate files, this formatter is easy and does it for you.

**How It Works**:

1. **Configure Flake8**: Set up Flake8 with the rules you want to enforce.
2. **Run the Flake8 Scout Rule Formatter**: Let the Flake8 Scout Rule do its magic.
2. **Collaborate**: Agree with your team that whenever someone touches a file with those # noqa comments, they'll take a moment to fix the underlying issues, if it makes sense to do so.

By following this approach, you can gradually improve your codebase, one commit at a time.

# How to run

```commandline
flake8 --format=scout .
```
*Note: The formatter is compatible with all valid Flake8 options. It is particularly beneficial to use this formatter with the `--select` and `--ignore` Flake8 options.*

### No prompt option
This option automatically update files with violations without prompting the user to review the violations.
```commandline
flake8 --format=scout --no-prompt .
```
