"""Test script for the Leicester Curve extractor implementation."""
import os
import sys

# Ensure the root project directory is on the system path for seamless module resolution
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from scrapers.leicester_curve.run_extractor import LeicesterCurveExtractor  # noqa: E402
from utils.logger import setup_logger  # noqa: E402

logger = setup_logger("test_leicester_curve", log_to_file=False)


def test_leicester_curve_pipeline():
    """Executes a framework validation run against the Leicester Curve extractor."""
    logger.info(" Starting Leicester Curve Pipeline Test Run")

    # Initialize using the framework configuration parameters
    extractor = LeicesterCurveExtractor(
        local_test=True,  # Restricts processing to a smaller subset of shows
        show_count=2,  # Limits processing to 2 shows for rapid end-to-end iteration
        save_csv_locally=True,  # Saves a verification file directly to the data/ folder
        csv_incremental_mode=False,
    )

    # Run the core pipeline lifecycle (Extract -> Save Raw -> Parse -> Validate Schema -> Save CSV)
    result = extractor.run()
    logger.info(f" Pipeline Test Completed. Result Summary: {result}")


if __name__ == "__main__":
    test_leicester_curve_pipeline()
