# frozen_string_literal: true

control 'influxdb.package.install' do
  title 'The required package should be installed'

  package_name = 'influxdb2'

  describe package(package_name) do
    it { should be_installed }
  end
end
