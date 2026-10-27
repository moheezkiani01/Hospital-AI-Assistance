import argparse
import json
from pathlib import Path

from app.db.base import Base
from app.db.database import SessionLocal, engine
from app.services import rag_eval_service, rag_index_service


def main():
    parser = argparse.ArgumentParser(
        description="Run measurable RAG retrieval evaluation."
    )
    parser.add_argument("--hospital-id", type=int, required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument(
        "--mode",
        choices=["embedding", "full"],
        default="embedding",
        help=(
            "embedding = no generative LLM calls; full = production reranker. "
            "Run embedding first."
        ),
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report", default=None)
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=15.0,
        help=(
            "Delay between full-mode cases. Default 15s is intentionally "
            "conservative for low/free-tier generation quotas."
        ),
    )
    parser.add_argument(
        "--provider-retry-wait-seconds",
        type=float,
        default=20.0,
        help="Wait before retrying a full-mode case when the reranker is temporarily unavailable.",
    )
    parser.add_argument(
        "--provider-max-retries",
        type=int,
        default=3,
        help="Retries for the same full-mode case after a temporary provider failure.",
    )
    parser.add_argument("--rebuild-first", action="store_true")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if args.rebuild_first:
            print(json.dumps(
                rag_index_service.rebuild_hospital_index(
                    db,
                    args.hospital_id,
                ),
                indent=2,
                default=str,
            ))

        health = rag_index_service.get_hospital_index_health(
            db,
            args.hospital_id,
        )
        print("RAG index health:")
        print(json.dumps(health, indent=2, default=str))

        cases = rag_eval_service.load_cases(args.cases)

        if args.mode == "embedding":
            report = rag_eval_service.run_embedding_evaluation(
                db,
                hospital_id=args.hospital_id,
                cases=cases,
                top_k=args.top_k,
                limit=args.limit,
            )
        else:
            report = rag_eval_service.run_full_evaluation(
                db,
                hospital_id=args.hospital_id,
                cases=cases,
                limit=args.limit,
                delay_seconds=max(0.0, args.delay_seconds),
                provider_retry_wait_seconds=max(
                    0.0,
                    args.provider_retry_wait_seconds,
                ),
                provider_max_retries=max(
                    0,
                    args.provider_max_retries,
                ),
            )

        print("\nRAG evaluation:")
        print(json.dumps({
            k: v
            for k, v in report.items()
            if k != "cases"
        }, indent=2))

        if args.report:
            report_path = Path(args.report)
            report_path.write_text(
                json.dumps(
                    report,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(f"\nDetailed report written to: {report_path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
