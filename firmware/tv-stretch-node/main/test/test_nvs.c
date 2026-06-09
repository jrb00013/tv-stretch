/**
 * Tests for NVS provisioning logic.
 * Verifies boundary conditions for provisioned state checks.
 */
#include "prov/tvs_nvs.h"
#include "unity.h"

TEST_CASE("nvs is provisioned returns false when nvs not openable", "[nvs]")
{
    /* Without initialized NVS, is_provisioned should return false. */
    TEST_ASSERT_FALSE(tvs_nvs_is_provisioned());
}
