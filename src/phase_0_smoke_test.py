# Databricks notebook source
"""Phase 0: verify that this bundle executes successfully on Databricks."""

from datetime import datetime, timezone

from pyspark.sql import SparkSession


spark = SparkSession.builder.getOrCreate()

result = (
    spark.range(1, 6)
    .selectExpr("id", "id * id AS squared")
    .orderBy("id")
    .collect()
)
actual = [(row["id"], row["squared"]) for row in result]
expected = [(1, 1), (2, 4), (3, 9), (4, 16), (5, 25)]

assert actual == expected, f"Unexpected Spark result: {actual}"

print("PHASE_0_SMOKE_TEST=PASSED")
print(f"executed_at_utc={datetime.now(timezone.utc).isoformat()}")
print(f"spark_version={spark.version}")
print(f"result={actual}")

dbutils.notebook.exit(  # type: ignore[name-defined]
    f"PHASE_0_SMOKE_TEST=PASSED; spark_version={spark.version}; result={actual}"
)
