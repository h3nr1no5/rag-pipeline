"""Evaluation pipeline CLI entry point."""
from src.evaluation.run import main

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
