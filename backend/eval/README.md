# Evaluation runner

Run `python backend/eval/run_eval.py` from the repository root (or `python eval/run_eval.py` from `backend`) to query repo 16 and write timestamped JSON and Markdown results under `backend/eval/results/`. Add `--include-empty-question` to exercise graceful handling of one invalid request.