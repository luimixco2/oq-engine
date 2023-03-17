# The Hazard Library
# Copyright (C) 2023 GEM Foundation
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Test cases 01–10 are based on the verification tests described in the
USGS ShakeMap 4.1 Manual.
Ref: Worden, C. B., E. M. Thompson, M. Hearne, and D. J. Wald (2020). 
ShakeMap Manual Online: technical manual, user’s guide, and software guide, 
U.S. Geological Survey. DOI: https://doi.org/10.5066/F7D21VPQ, see
https://usgs.github.io/shakemap/manual4_0/tg_verification.html`.
"""
import unittest

import matplotlib.pyplot as plt
import numpy

from openquake.hazardlib.calc.conditioned_gmfs import \
    get_conditioned_mean_and_covariance
from openquake.hazardlib.cross_correlation import GodaAtkinson2009
from openquake.hazardlib.tests.calc import \
    _conditioned_gmfs_test_data as test_data


class SetUSGSTestCase(unittest.TestCase):
    def test_case_01(self):
        case_name = "test_case_01"
        rupture = test_data.RUP
        gmm = test_data.ZeroMeanGMM()
        station_sitecol = test_data.CASE01_STATION_SITECOL
        station_data = test_data.CASE01_STATION_DATA
        observed_imt_strs = test_data.CASE01_OBSERVED_IMTS
        target_sitecol = test_data.CASE01_TARGET_SITECOL
        target_imts = test_data.CASE01_TARGET_IMTS
        spatial_correl = test_data.DummySpatialCorrelationModel()
        cross_correl_between = GodaAtkinson2009()
        cross_correl_within = test_data.DummyCrossCorrelationWithin()
        maximum_distance = test_data.MAX_DIST
        mean_covs = get_conditioned_mean_and_covariance(
            rupture, gmm, station_sitecol, station_data,
            observed_imt_strs, target_sitecol, target_imts,
            spatial_correl, cross_correl_between, cross_correl_within,
            maximum_distance)
        mu = mean_covs[0][target_imts[0].string].flatten()
        sig = numpy.sqrt(numpy.diag(mean_covs[1][target_imts[0].string]))
        numpy.testing.assert_allclose(numpy.zeros_like(mu), mu)
        numpy.testing.assert_almost_equal(numpy.min(sig), 0)
        assert numpy.max(sig) > 0.8 and numpy.max(sig) < 1.0
        plot_test_results(target_sitecol.lons, mu, sig, target_imts[0].string, case_name)
        
    def test_case_02(self):
        case_name = "test_case_02"
        rupture = test_data.RUP
        gmm = test_data.ZeroMeanGMM()
        station_sitecol = test_data.CASE02_STATION_SITECOL
        station_data = test_data.CASE02_STATION_DATA
        observed_imt_strs = test_data.CASE02_OBSERVED_IMTS
        target_sitecol = test_data.CASE02_TARGET_SITECOL
        target_imts = test_data.CASE02_TARGET_IMTS
        spatial_correl = test_data.DummySpatialCorrelationModel()
        cross_correl_between = GodaAtkinson2009()
        cross_correl_within = test_data.DummyCrossCorrelationWithin()
        maximum_distance = test_data.MAX_DIST
        mean_covs = get_conditioned_mean_and_covariance(
            rupture, gmm, station_sitecol, station_data,
            observed_imt_strs, target_sitecol, target_imts,
            spatial_correl, cross_correl_between, cross_correl_within,
            maximum_distance)
        mu = mean_covs[0][target_imts[0].string].flatten()
        sig = numpy.sqrt(numpy.diag(mean_covs[1][target_imts[0].string]))
        numpy.testing.assert_allclose(numpy.min(mu), -1, rtol=1e-4)
        numpy.testing.assert_allclose(numpy.max(mu), 1, rtol=1e-4)
        numpy.testing.assert_allclose(numpy.min(numpy.abs(mu)), 0, atol=1e-4)
        numpy.testing.assert_allclose(numpy.min(sig), 0, atol=1e-4)
        assert numpy.max(sig) > 0.8 and numpy.max(sig) < 1.0
        plot_test_results(target_sitecol.lons, mu, sig, target_imts[0].string, case_name)

    def test_case_03(self):
        case_name = "test_case_03"
        rupture = test_data.RUP
        gmm = test_data.ZeroMeanGMM()
        station_sitecol = test_data.CASE03_STATION_SITECOL
        station_data = test_data.CASE03_STATION_DATA
        observed_imt_strs = test_data.CASE03_OBSERVED_IMTS
        target_sitecol = test_data.CASE03_TARGET_SITECOL
        target_imts = test_data.CASE03_TARGET_IMTS
        spatial_correl = test_data.DummySpatialCorrelationModel()
        cross_correl_between = GodaAtkinson2009()
        cross_correl_within = test_data.DummyCrossCorrelationWithin()
        maximum_distance = test_data.MAX_DIST
        mean_covs = get_conditioned_mean_and_covariance(
            rupture, gmm, station_sitecol, station_data,
            observed_imt_strs, target_sitecol, target_imts,
            spatial_correl, cross_correl_between, cross_correl_within,
            maximum_distance)
        mu = mean_covs[0][target_imts[0].string].flatten()
        sig = numpy.sqrt(numpy.diag(mean_covs[1][target_imts[0].string]))
        numpy.testing.assert_allclose(numpy.min(mu), 0.36, rtol=1e-4)
        numpy.testing.assert_allclose(numpy.max(mu), 1, rtol=1e-4)
        numpy.testing.assert_allclose(numpy.min(sig), 0, rtol=1e-4)
        numpy.testing.assert_allclose(numpy.max(sig), numpy.sqrt(0.8704), rtol=1e-4)
        plot_test_results(target_sitecol.lons, mu, sig, target_imts[0].string, case_name)

    def test_case_04(self):
        case_name = "test_case_04"
        rupture = test_data.RUP
        gmm = test_data.ZeroMeanGMM()
        station_sitecol = test_data.CASE04_STATION_SITECOL
        station_data = test_data.CASE04_STATION_DATA
        observed_imt_strs = test_data.CASE04_OBSERVED_IMTS
        target_sitecol = test_data.CASE04_TARGET_SITECOL
        target_imts = test_data.CASE04_TARGET_IMTS
        spatial_correl = test_data.DummySpatialCorrelationModel()
        cross_correl_between = GodaAtkinson2009()
        cross_correl_within = test_data.DummyCrossCorrelationWithin()
        maximum_distance = test_data.MAX_DIST
        mean_covs = get_conditioned_mean_and_covariance(
            rupture, gmm, station_sitecol, station_data,
            observed_imt_strs, target_sitecol, target_imts,
            spatial_correl, cross_correl_between, cross_correl_within,
            maximum_distance)
        mu = mean_covs[0][target_imts[0].string].flatten()
        sig = numpy.sqrt(numpy.diag(mean_covs[1][target_imts[0].string]))
        numpy.testing.assert_allclose(numpy.min(mu), 0.36, rtol=1e-4)
        numpy.testing.assert_allclose(numpy.max(mu), 1)
        numpy.testing.assert_allclose(numpy.min(sig), 0, atol=1e-4)
        numpy.testing.assert_allclose(numpy.max(sig), numpy.sqrt(0.8704), rtol=1e-4)
        plot_test_results(target_sitecol.lons, mu, sig, target_imts[0].string, case_name)

    def test_case_05(self):
        case_name = "test_case_05"
        rupture = test_data.RUP
        gmm = test_data.ZeroMeanGMM()
        station_sitecol = test_data.CASE05_STATION_SITECOL
        station_data = test_data.CASE05_STATION_DATA
        observed_imt_strs = test_data.CASE05_OBSERVED_IMTS
        target_sitecol = test_data.CASE05_TARGET_SITECOL
        target_imts = test_data.CASE05_TARGET_IMTS
        spatial_correl = test_data.DummySpatialCorrelationModel()
        cross_correl_between = GodaAtkinson2009()
        cross_correl_within = test_data.DummyCrossCorrelationWithin()
        maximum_distance = test_data.MAX_DIST
        mean_covs = get_conditioned_mean_and_covariance(
            rupture, gmm, station_sitecol, station_data,
            observed_imt_strs, target_sitecol, target_imts,
            spatial_correl, cross_correl_between, cross_correl_within,
            maximum_distance)
        mu = mean_covs[0][target_imts[0].string].flatten()
        sig = numpy.sqrt(numpy.diag(mean_covs[1][target_imts[0].string]))
        numpy.testing.assert_allclose(numpy.zeros_like(mu), mu, atol=1e-4)
        numpy.testing.assert_allclose(numpy.min(sig), 0, atol=1e-4)
        numpy.testing.assert_allclose(numpy.max(sig), numpy.sqrt(0.8704), rtol=1e-4)
        plot_test_results(target_sitecol.lons, mu, sig, target_imts[0].string, case_name)

# Useful for debugging purposes. Recreates the plots on
# https://usgs.github.io/shakemap/manual4_0/tg_verification.html
# Original code is from the ShakeMap XTestPlot module:
# https://github.com/usgs/shakemap/blob/main/shakemap/coremods/xtestplot.py
def plot_test_results(lons, means, stds, target_imt, case_name):
    fig, ax = plt.subplots(2, sharex=True, figsize=(10, 8))
    plt.subplots_adjust(hspace=0.1)
    ax[0].plot(lons, means, color="k", label="mean")
    ax[0].plot(
        lons, means + stds, "--b", label="mean +/- stddev"
    )
    ax[0].plot(lons, means - stds, "--b")
    ax[1].plot(lons, stds, "-.r", label="stddev")
    plt.xlabel("Longitude")
    ax[0].set_ylabel(f"Mean ln({target_imt}) (g)")
    ax[1].set_ylabel(f"Stddev ln({target_imt}) (g)")
    ax[0].legend(loc="best")
    ax[1].legend(loc="best")
    ax[0].set_title(case_name)
    ax[0].grid()
    ax[1].grid()
    ax[1].set_ylim(bottom=0)
    plt.show()