using System.Windows.Controls;
using System.Windows.Data;

namespace VPNSL.Windows;

public partial class MainWindow
{
    private void RouteSearchBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        var query = RouteSearchBox.Text.Trim();
        var view = CollectionViewSource.GetDefaultView(_settings.Routes);
        if (view is null) return;

        view.Filter = item =>
        {
            if (string.IsNullOrWhiteSpace(query)) return true;
            if (item is not RouteProfile profile) return false;

            if (profile.Name.Contains(query, StringComparison.OrdinalIgnoreCase)) return true;
            if (profile.TargetDisplay.Contains(query, StringComparison.OrdinalIgnoreCase)) return true;

            return profile.Routes.Any(route =>
                route.Contains(query, StringComparison.OrdinalIgnoreCase));
        };

        view.Refresh();
    }
}
