using System.Windows;
using System.Windows.Threading;

namespace VPNSL.Windows;

public partial class MainWindow
{
    private bool _connectionStateFixAttached;

    protected override void OnContentRendered(EventArgs e)
    {
        base.OnContentRendered(e);
        if (_connectionStateFixAttached) return;
        _connectionStateFixAttached = true;

        // ConnectButton_Click disables the button before ConnectAsync starts.
        // Re-enable it as soon as the engine enters the connecting state so a
        // second click can cancel the in-progress connection via IsActive.
        _engine.StatusChanged += OnConnectionStateForButton;
    }

    private void OnConnectionStateForButton(string status)
    {
        Dispatcher.BeginInvoke(DispatcherPriority.Normal, new Action(() =>
        {
            if (status.Equals("Подключение", StringComparison.Ordinal))
            {
                ConnectButton.Content = "Отменить подключение";
                ConnectButton.IsEnabled = true;
            }
            else if (status.Equals("Подключено", StringComparison.Ordinal))
            {
                ConnectButton.Content = "Отключить";
                ConnectButton.IsEnabled = true;
            }
            else if (status.Equals("Отключено", StringComparison.Ordinal))
            {
                ConnectButton.Content = "Подключить";
                ConnectButton.IsEnabled = true;
            }
        }));
    }
}