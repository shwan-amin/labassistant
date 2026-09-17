# Lab Assistant for VS Code

Check your **understanding** of the code you're writing, not just whether it passes.

Highlight code in your lab, right-click and choose **Lab Assistant: Check my understanding**. Lab Assistant:

- looks at your selection in the context of your project and runs your tests;
- highlights lines that suggest a possible gap in a programming concept (for example base cases in recursion);
- asks you a **guiding question** instead of giving you the answer;
- links confirmed gaps to the exact moment in a lecture recording and the matching slide;
- remembers how secure you are with each concept (visible to markers in the dashboard).

It **never writes solutions or corrected code**.

## Requirements

This extension is the front end of a research prototype. It needs the Lab Assistant backend running locally:

```bash
uv run labassistant-api     # from the Lab Assistant repository
```

The backend sends your selected code and project files to the AI service it is configured with. You're asked for consent the first time.

## Settings

| Setting | Default | |
|---|---|---|
| `labAssistant.backendUrl` | `http://127.0.0.1:8000` | Where the local backend runs |
| `labAssistant.studentId` | *(backend default)* | Identifies your learner model |
| `labAssistant.skipQuestioning` | `false` | Show feedback directly instead of asking questions |
| `labAssistant.maxFileBytes` | `200000` | Larger files are not sent |
| `labAssistant.maxProjectBytes` | `2000000` | Cap on the total size sent |

## Commands

- **Lab Assistant: Check my understanding** (also in the editor right-click menu when text is selected)
- **Lab Assistant: Show panel**
- **Lab Assistant: Reset consent to send code**

## Credits

Lecture links refer to MIT OpenCourseWare 6.0001 (Fall 2016), Lecture 6, by Eric Grimson, John Guttag and Ana Bell, licensed CC BY-NC-SA 4.0.
