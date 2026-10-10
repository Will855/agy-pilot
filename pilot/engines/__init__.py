"""
Motores de ejecución para los diferentes casos de uso de agy-pilot.
"""

from pilot.engines.convergence import (
    CumulativeMemory,
    Quadrant,
    partition_into_quadrants,
    run_convergence_loop,
)

