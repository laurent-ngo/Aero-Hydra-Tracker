import pytest
from unittest.mock import MagicMock, patch
from elevation import ElevationProvider  # Replace with your actual filename

@pytest.fixture
def mock_provider():
    """Fixture to create a provider with a mocked dataset."""
    with patch('rasterio.open') as mock_open:
        # Mock the dataset behavior
        mock_dataset = MagicMock()
        mock_dataset.bounds.left = 0
        mock_dataset.bounds.right = 10
        mock_dataset.bounds.bottom = 40
        mock_dataset.bounds.top = 50
        
        # Mock the coordinate index conversion
        mock_dataset.index.return_value = (5, 5) # returns row, col
        
        # Mock the data reading (returns a 2D numpy-like array)
        mock_dataset.read.return_value = MagicMock()
        mock_dataset.read.return_value.__getitem__.return_value = 150.0
        
        mock_open.return_value = mock_dataset
        yield ElevationProvider("dummy.tif"), mock_dataset

def test_get_elevation_valid(mock_provider):
    provider, mock_ds = mock_provider
    # Test a point inside the bounds
    elevation = provider.get_elevation(45.0, 5.0)
    assert elevation == 150.0
    mock_ds.index.assert_called_with(5.0, 45.0)

def test_get_elevation_out_of_bounds(mock_provider):
    provider, _ = mock_provider
    # Test a point outside (North of 50.0)
    elevation = provider.get_elevation(60.0, 5.0)
    assert elevation is None

def test_close_handle(mock_provider):
    provider, mock_ds = mock_provider
    provider.close()
    mock_ds.close.assert_called_once()