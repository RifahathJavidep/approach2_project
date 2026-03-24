# PRISM — Training Guide

This folder contains scripts to train the two AI models used by PRISM:

| Script | Trains | Output |
|--------|--------|--------|
| `train_br.py` | Business Requirement extractor (DSPy classifier) | `br_extractor.json` |
| `train_testcases.py` | Test Case generator (DSPy scenario generator) | `tc_generator.json` |

---

## Prerequisites

1. **Python 3.10 or 3.11**
2. **Install dependencies** (from project root):
   ```bash
   pip install -r extraction-service/requirements.txt
   ```
3. **Set your API key** — create a `.env` file in the project root (copy from `.env.example`):
   ```
   GROQ_API_KEY=your_groq_api_key_here
   ```
4. **Run from the project root directory**, not from inside `training/`:
   ```bash
   # Correct:
   python training/train_br.py --gt-dir data/groundtruth/my-project/

   # Wrong:
   cd training && python train_br.py
   ```

---

## Training the BR Extractor

### What it does
Trains the `RequirementClassifier` — the model that decides whether a piece of text is a genuine business requirement or noise (vague statements, service items, technical internals).

### Prepare your ground truth data

Create a JSON file in `data/groundtruth/<your-project>/` with your real requirements:

```json
[
  {
    "title": "User Login",
    "description": "Users can log in with email and password. Show error message on failure.",
    "type": "Functional"
  },
  {
    "title": "Dashboard Screen",
    "description": "Main dashboard with KPI widgets showing revenue, open tickets, and user activity.",
    "type": "UI"
  }
]
```

Excel files (`.xlsx`) are also supported with columns: `Title`, `Description`, `Type`.

### Run training

**Option A — with ground truth directory:**
```bash
python training/train_br.py --gt-dir data/groundtruth/my-project/
```

**Option B — with config file (recommended for multiple projects):**
```bash
python training/train_br.py --config training/my_project_config.yaml
```

**Option C — all options:**
```bash
python training/train_br.py \
  --gt-dir data/groundtruth/my-project/ \
  --output-dir data/trained_models/my-project/ \
  --lm groq/llama-3.1-70b-versatile
```

### What to change for a new project

| What | Where to change |
|------|----------------|
| Ground truth data | Add your `.json` or `.xlsx` files to `data/groundtruth/<project-name>/` |
| Output location | `--output-dir data/trained_models/<project-name>/` |
| Language model | `--lm groq/llama-3.1-70b-versatile` (or edit `config.yaml`) |

### Output
Saves `br_extractor.json` to `--output-dir`. This file is loaded automatically by the extraction pipeline at runtime.

---

## Training the Test Case Generator

### What it does
Trains the `ScenarioGeneratorModule` — the model that generates test cases from business requirements. It learns from your existing (ground truth) test cases to match your team's format and detail level.

### Prepare your ground truth data

You need two things:

**1. Requirements JSON** (output from the BR extraction pipeline, or hand-crafted):
```json
[
  {
    "title": "User Login",
    "description": "Users can log in with email and password."
  }
]
```

**2. Ground truth test cases JSON** in `data/groundtruth/<your-project>/test_cases/`:
```json
{
  "test_cases": [
    {
      "title": "User Login - Happy Path",
      "description": "Verify successful login with valid credentials",
      "steps": [
        { "action": "Navigate to login page", "expected": "Login form is displayed" },
        { "action": "Enter valid email and password", "expected": "Fields are filled" },
        { "action": "Click Login button", "expected": "User is redirected to dashboard" }
      ]
    }
  ]
}
```

### Run training

**Option A — with explicit file paths:**
```bash
python training/train_testcases.py \
  --gt-dir data/groundtruth/my-project/test_cases/ \
  --req-file data/outputs/my-project/requirements.json
```

**Option B — with config file:**
```bash
python training/train_testcases.py --config training/my_project_config.yaml
```

**Option C — all options:**
```bash
python training/train_testcases.py \
  --gt-dir data/groundtruth/my-project/test_cases/ \
  --req-file data/outputs/my-project/requirements.json \
  --output-dir data/trained_models/my-project/ \
  --lm groq/llama-3.1-70b-versatile
```

### What to change for a new project

| What | Where to change |
|------|----------------|
| Ground truth test cases | Add `.json` files to `data/groundtruth/<project>/test_cases/` |
| Requirements file | `--req-file data/outputs/<project>/requirements.json` |
| Output location | `--output-dir data/trained_models/<project>/` |
| Language model | `--lm groq/llama-3.1-70b-versatile` |

### Output
Saves `tc_generator.json` to `--output-dir`. This file is loaded automatically by the testgen pipeline at runtime.

---

## Multiple Projects — Using a Config File

For multiple projects, use a YAML config file instead of CLI flags. Copy `config_example.yaml` and edit it:

```bash
cp training/config_example.yaml training/project_abc_config.yaml
# Edit training/project_abc_config.yaml with your paths
python training/train_br.py --config training/project_abc_config.yaml
python training/train_testcases.py --config training/project_abc_config.yaml
```

See [config_example.yaml](config_example.yaml) for all available options.

---

## Where Trained Models Are Used

| Model file | Used by |
|------------|---------|
| `br_extractor.json` | `extraction-service` — loaded by `extraction/generators/trained_extractor.py` |
| `tc_generator.json` | `testgen-service` — loaded by `testgen/scenario_generator.py` |

After training, place the model files in the directory where the service can find them, or set the path in `config.yaml`.

---

## Troubleshooting

**`GROQ_API_KEY not set`** — Create a `.env` file in the project root with `GROQ_API_KEY=your_key`.

**`No training examples could be matched`** — Make sure your requirements and ground truth test cases have overlapping topics. The matcher uses text similarity — vague or very short descriptions may not match well.

**`ModuleNotFoundError`** — Run from the project root directory, not from inside `training/`.
