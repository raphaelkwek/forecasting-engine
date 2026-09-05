"""Unit tests for the extract panel's pure helpers. No Streamlit state, no network."""

from __future__ import annotations

import pytest

from extract_panel import MANUAL_COLUMNS, _guess_manual_column, _manual_options


class TestGuessManualColumn:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            # Alias stems map to the bond column.
            ("legatruu.csv", "bond_index_global_agg"),
            ("legatruu index.csv", "bond_index_global_agg"),
            ("bloomberg global aggregate.csv", "bond_index_global_agg"),
            # Bloomberg's own export stem: underscores and a "price" suffix.
            ("Bloomberg_Global_Agg_Bond_Index_Price.csv", "bond_index_global_agg"),
            # Aliases map to the FX-vol column.
            ("fximplvol.csv", "fx_impl_vol"),
            ("fx_impl_vol.csv", "fx_impl_vol"),
            ("g7 fx vol.csv", "fx_impl_vol"),
            # A known column name maps to itself.
            ("bond_index_global_agg.csv", "bond_index_global_agg"),
        ],
    )
    def test_maps_aliases(self, filename, expected):
        assert _guess_manual_column(filename) == expected

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("LEGATRUU.CSV", "bond_index_global_agg"),
            ("LEGATRUU INDEX.CSV", "bond_index_global_agg"),
            ("Bloomberg Global Aggregate.csv", "bond_index_global_agg"),
            ("FXIMPLVOL.CSV", "fx_impl_vol"),
            ("G7 FX VOL.csv", "fx_impl_vol"),
            (" legatruu .CSV ", "bond_index_global_agg"),  # surrounding whitespace
        ],
    )
    def test_is_case_insensitive(self, filename, expected):
        assert _guess_manual_column(filename) == expected

    def test_strips_only_the_last_extension(self):
        # "g7.fx.vol" is not an alias — only a trailing ".csv" is stripped; the
        # untouched stem is itself a fresh column.
        assert _guess_manual_column("g7.fx.vol.csv") == "g7.fx.vol"
        assert _guess_manual_column("legatruu") == "bond_index_global_agg"

    def test_unrecognised_file_becomes_a_new_column(self):
        # The dropzone sells unrecognised signals as their own new columns, so
        # the guess must name the stem (as _manual_options offers it) rather
        # than silently overwrite an existing column's data.
        assert _guess_manual_column("some_other_signal.csv") == "some_other_signal"
        assert _guess_manual_column(
            "My_Custom_Indicator.csv"
        ) == "My_Custom_Indicator"  # original case preserved

    def test_only_alias_filenames_overwrite_known_columns(self):
        assert _guess_manual_column("LEGATRUU INDEX.csv") == "bond_index_global_agg"
        assert _guess_manual_column("Bloomberg Global Aggregate.csv") == "bond_index_global_agg"
        assert _guess_manual_column("FXIMPLVOL.csv") == "fx_impl_vol"

    def test_empty_filename_falls_back_to_first_manual_column(self):
        assert _guess_manual_column("") == MANUAL_COLUMNS[0]


class TestManualOptions:
    def test_known_stem_adds_no_fresh_column_option(self):
        # "fx_impl_vol" already names a manual column, so selecting it is an
        # override; a duplicate "new column" option would be pointless.
        assert _manual_options("fx_impl_vol.csv") == list(MANUAL_COLUMNS)

    def test_unknown_stem_adds_a_fresh_column_option(self):
        assert _manual_options("legatruu.csv") == [
            "bond_index_global_agg",
            "fx_impl_vol",
            "legatruu",
        ]