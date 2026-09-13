using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace VPNSL.Windows;

public partial class MainWindow
{
    private bool _brandingApplied;

    static MainWindow()
    {
        EventManager.RegisterClassHandler(
            typeof(MainWindow),
            FrameworkElement.LoadedEvent,
            new RoutedEventHandler(OnBrandingLoaded));
    }

    private static void OnBrandingLoaded(object sender, RoutedEventArgs e)
    {
        if (sender is not MainWindow window || window._brandingApplied)
        {
            return;
        }

        window._brandingApplied = true;

        var iconUri = new Uri("pack://application:,,,/Assets/VPNSL.ico", UriKind.Absolute);
        var decoder = BitmapDecoder.Create(
            iconUri,
            BitmapCreateOptions.PreservePixelFormat,
            BitmapCacheOption.OnLoad);
        var icon = decoder.Frames.OrderByDescending(frame => frame.PixelWidth).First();

        window.Icon = icon;

        foreach (var textBlock in FindVisualChildren<TextBlock>(window)
                     .Where(text => string.Equals(text.Text, "V", StringComparison.Ordinal)))
        {
            ReplacePlaceholderWithIcon(textBlock, icon);
        }
    }

    private static void ReplacePlaceholderWithIcon(TextBlock placeholder, ImageSource icon)
    {
        var parent = VisualTreeHelper.GetParent(placeholder);

        if (parent is Border directBorder)
        {
            placeholder.Visibility = Visibility.Collapsed;
            directBorder.Background = CreateIconBrush(icon);
            return;
        }

        if (parent is Grid grid && VisualTreeHelper.GetParent(grid) is Border outerBorder)
        {
            foreach (UIElement child in grid.Children)
            {
                child.Visibility = Visibility.Collapsed;
            }

            outerBorder.Background = CreateIconBrush(icon);
        }
    }

    private static ImageBrush CreateIconBrush(ImageSource icon) => new(icon)
    {
        Stretch = Stretch.Uniform,
        AlignmentX = AlignmentX.Center,
        AlignmentY = AlignmentY.Center
    };

    private static IEnumerable<T> FindVisualChildren<T>(DependencyObject root)
        where T : DependencyObject
    {
        for (var i = 0; i < VisualTreeHelper.GetChildrenCount(root); i++)
        {
            var child = VisualTreeHelper.GetChild(root, i);
            if (child is T typed)
            {
                yield return typed;
            }

            foreach (var descendant in FindVisualChildren<T>(child))
            {
                yield return descendant;
            }
        }
    }
}
