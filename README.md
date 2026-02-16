# Requirements Extraction - Trained Approach

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy `.env.template` to `.env` and add your GROQ API key:
```bash
cp .env.template .env
# Edit .env and add your key
```

3. Place your files:
   - Input PDF → `input/` folder
   - Ground truth Excel → `ground_truth/` folder

4. Update `config/config.json` with your file names

## Run (VS Code)

1. Open `extract_requirements.py`
2. Press F5 to run extraction
3. Open `evaluate.py`
4. Press F5 to run evaluation

## Run (Terminal)

```bash
python extract_requirements.py
python evaluate.py
```

## Folder Structure

```
approach2_project/
├── input/                    # Place your PDF here
├── output/                   # Results saved here
├── ground_truth/             # Place Excel ground truth here
├── config/
│   └── config.json          # Configuration
├── extract_requirements.py  # Main extraction script
├── evaluate.py              # Evaluation script
├── .env                     # Your API keys (create from .env.template)
└── requirements.txt         # Python dependencies
```

## Training Data

- 8 positive examples (user features)
- 11 negative examples (implementation details, NFRs)
- Domain-agnostic: teaches "requirement vs non-requirement"

## Output Files

- `output/{project}_requirements.json` - Extracted requirements
- `output/{project}_evaluation.json` - Evaluation metrics
# approach2_project
