@echo off
echo Packaging automation-dotnet project into clean zip...
powershell -Command "Compress-Archive -Path AutomationDotNet.csproj, App.xaml, App.xaml.cs, MainWindow.xaml, MainWindow.xaml.cs, PickPointWindow.xaml, PickPointWindow.xaml.cs, Models, Services, build.bat, README.md, .gitignore -DestinationPath automation-dotnet.zip -Force"
echo Created automation-dotnet.zip successfully!
pause
